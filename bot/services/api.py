from __future__ import annotations

import asyncio
import hashlib
import json
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from bot.config import settings
from bot.utils.logger import get_logger

logger = get_logger(__name__)

KYIV_TZ = settings.timezone

_schedule_cache: OrderedDict[str, tuple[datetime, Any]] = OrderedDict()
_image_cache: OrderedDict[str, tuple[datetime, bytes]] = OrderedDict()
CACHE_TTL = timedelta(minutes=2)
MAX_CACHE_SIZE = 100

# Locks protecting concurrent access to caches and commit state
_schedule_cache_lock: asyncio.Lock = asyncio.Lock()
_image_cache_lock: asyncio.Lock = asyncio.Lock()
_commit_state_lock: asyncio.Lock = asyncio.Lock()

# Chart render mode: False = on_change (cache), True = on_demand (always re-render)
_chart_render_on_demand: bool = False


def set_chart_render_mode(on_demand: bool) -> None:
    """Update the in-memory chart render mode flag (persisted in DB by the caller)."""
    global _chart_render_on_demand
    _chart_render_on_demand = on_demand


def get_chart_render_on_demand() -> bool:
    return _chart_render_on_demand

_http_client: aiohttp.ClientSession | None = None
_last_commit_sha: str | None = None
_last_etag: str | None = None


def get_last_commit_sha() -> str | None:
    """Return the last known commit SHA (used to pin raw URLs to a specific commit)."""
    return _last_commit_sha


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

    Returns a ``(has_update, new_sha)`` tuple:
    - ``(True, None)``   — initial run or API error; always run a full check.
    - ``(True, sha)``    — new commit detected; ``_last_commit_sha`` is already
      updated so callers do **not** need to call any confirm function.
    - ``(False, None)``  — no new commits; skip the check.
    """
    global _last_commit_sha, _last_etag
    async with _commit_state_lock:
        return await _check_source_repo_updated_inner()


async def _check_source_repo_updated_inner() -> tuple[bool, str | None]:
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
                            asyncio.get_running_loop().create_task(
                                _save_commit_state(), name="save_commit_state"
                            )
                        except RuntimeError:
                            pass
                        return True, None
                    if new_sha != _last_commit_sha:
                        logger.info("New commit detected: %s -> %s", _last_commit_sha[:8], new_sha[:8])
                        _last_commit_sha = new_sha
                        try:
                            # create_task is fire-and-forget by design here: the
                            # state is already in-memory (_last_commit_sha) and the
                            # DB write is best-effort persistence for restart recovery.
                            # We name the task so it shows up in asyncio debug logs.
                            asyncio.get_running_loop().create_task(
                                _save_commit_state(), name="save_commit_state"
                            )
                        except RuntimeError:
                            logger.debug("No running event loop; commit state save deferred")
                        return True, new_sha
                    logger.debug("No new commits (SHA: %s)", new_sha[:8])
                    return False, None
                # Empty or non-list response body — trigger a full check
                logger.warning("GitHub API returned empty or non-list commits body, falling back to full fetch")
                return True, None
            else:
                logger.warning("GitHub Commits API returned %d, falling back to full fetch", resp.status)
                return True, None
    except Exception as e:
        logger.warning("GitHub Commits API check failed: %s, falling back to full fetch", e)
        return True, None
    finally:
        if _owned:
            await _session.close()


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
    async with _schedule_cache_lock:
        if not force_refresh and cache_key in _schedule_cache:
            cached_at, data = _schedule_cache[cache_key]
            if now - cached_at < effective_ttl:
                _schedule_cache.move_to_end(cache_key)
                return data

    url = settings.DATA_URL_TEMPLATE.replace('{region}', region)
    if force_refresh and _last_commit_sha:
        # Pin the URL to the exact commit SHA so the CDN returns the right
        # version immediately, instead of a stale /main/ cached copy.
        url = url.replace("/main/", f"/{_last_commit_sha}/")
    req_headers: dict[str, str] = {"User-Agent": "SvitloCheck-Bot/4.0"}

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
                    async with _schedule_cache_lock:
                        if len(_schedule_cache) >= MAX_CACHE_SIZE:
                            _schedule_cache.popitem(last=False)
                        _schedule_cache[cache_key] = (now, data)
                        _schedule_cache.move_to_end(cache_key)
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


async def invalidate_image_cache(region: str, queue: str) -> None:
    """Remove the L1 in-memory entry for the given region/queue.

    The Redis (L2) entry is deleted separately by the scheduler's
    ``_prerender_chart`` coroutine, which runs right after this call and
    immediately stores a freshly rendered replacement.
    """
    cache_key = f"{region}_{queue}"
    async with _image_cache_lock:
        if cache_key in _image_cache:
            del _image_cache[cache_key]
            logger.debug("L1 image cache invalidated for %s/%s", region, queue)


async def _l1_store_async(cache_key: str, now: datetime, data: bytes) -> None:
    """Write *data* into the L1 in-memory cache (async-safe)."""
    async with _image_cache_lock:
        if len(_image_cache) >= MAX_CACHE_SIZE:
            _image_cache.popitem(last=False)
        _image_cache[cache_key] = (now, data)
        _image_cache.move_to_end(cache_key)


async def fetch_schedule_image(
    region: str,
    queue: str,
    schedule_data: dict | None = None,
) -> bytes | None:
    """Return a PNG chart image for the given region/queue.

    Lookup chain
    ────────────
    1. L1 in-memory cache (2 min TTL) — fastest path, no I/O.
    2. L2 Redis cache (25 h TTL)      — pre-rendered on last schedule change.
       On hit the result is also written back to L1 so subsequent requests
       within the same hot window are served without a Redis round-trip.
    3. Local generation via Pillow    — requires *schedule_data*.
       Result is stored in both caches so the next N users get it for free.
    4. GitHub fallback                — fetches a pre-built PNG from the
       upstream repository. Result is stored in both caches.
    """
    from bot.services import chart_cache

    # ── on_demand mode: always render fresh, skip all caches ──────────────────
    if _chart_render_on_demand and schedule_data is not None:
        from bot.services.chart_generator import generate_schedule_chart
        return await generate_schedule_chart(region, queue, schedule_data)

    cache_key = f"{region}_{queue}"
    now = datetime.now()

    # ── L1: in-memory ─────────────────────────────────────────────────────────
    async with _image_cache_lock:
        if cache_key in _image_cache:
            cached_at, data = _image_cache[cache_key]
            if now - cached_at < CACHE_TTL:
                _image_cache.move_to_end(cache_key)
                return data

    # ── L2: Redis ─────────────────────────────────────────────────────────────
    redis_data = await chart_cache.get(region, queue)
    if redis_data:
        await _l1_store_async(cache_key, now, redis_data)
        return redis_data

    # ── Generate locally ──────────────────────────────────────────────────────
    if schedule_data is not None:
        from bot.services.chart_generator import generate_schedule_chart
        generated = await generate_schedule_chart(region, queue, schedule_data)
        if generated:
            await chart_cache.store(region, queue, generated)
            await _l1_store_async(cache_key, now, generated)
            return generated
        logger.warning("Local chart generation failed for %s/%s — falling back to GitHub", region, queue)

    # ── Fallback: GitHub pre-rendered PNG ─────────────────────────────────────
    queue_dashed = queue.replace(".", "-")
    url = settings.IMAGE_URL_TEMPLATE.replace('{region}', region).replace('{queue}', queue_dashed)
    if _last_commit_sha:
        url = url.replace("/main/", f"/{_last_commit_sha}/")

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
                headers={"User-Agent": "SvitloCheck-Bot/4.0"},
            ) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    await chart_cache.store(region, queue, data)
                    await _l1_store_async(cache_key, now, data)
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

    dtek_updated_at: str | None = fact.get("update")  # "DD.MM.YYYY HH:MM" from DTEK source
    return {"hasData": len(events) > 0, "events": events, "queue": queue, "dtek_updated_at": dtek_updated_at}


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
            is_possible = any(events[k].get("isPossible", False) for k in range(i, j))
            return {
                "type": "power_on",
                "time": final_end.isoformat(),
                "startTime": ev["start"],
                "endTime": None,
                "minutes": int((final_end - now).total_seconds() / 60),
                "isPossible": is_possible,
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
    return hashlib.sha256(data.encode()).hexdigest()
