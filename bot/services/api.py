from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any

import aiohttp

from bot.config import settings
from bot.utils.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from bot.utils.logger import get_logger
from bot.utils.metrics import SCHEDULE_FETCH_DURATION, SCHEDULE_FETCH_ERRORS

logger = get_logger(__name__)

# Maximum response sizes — guards against bloated/malicious payloads causing OOM.
_MAX_JSON_RESPONSE = 5 * 1024 * 1024   # 5 MB (schedule JSON)
_MAX_COMMIT_RESPONSE = 512 * 1024       # 512 KB (GitHub commits list)
_MAX_IMAGE_RESPONSE = 15 * 1024 * 1024  # 15 MB (pre-rendered PNG chart)

# Circuit breaker for the upstream schedule data source.
# Opens after 5 consecutive fetch failures; re-probes after 60 s.
_schedule_api_breaker = CircuitBreaker(
    name="schedule_api",
    fail_max=5,
    reset_timeout=60.0,
    exclude=(asyncio.CancelledError,),
)

KYIV_TZ = settings.timezone

_schedule_cache: OrderedDict[str, tuple[datetime, Any]] = OrderedDict()
_image_cache: OrderedDict[str, tuple[datetime, bytes]] = OrderedDict()
_queue_source_update_cache: OrderedDict[str, tuple[datetime, str | None]] = OrderedDict()
_queue_source_update_etags: dict[str, str] = {}
CACHE_TTL = timedelta(minutes=2)
QUEUE_SOURCE_UPDATE_TTL = timedelta(minutes=10)
MAX_CACHE_SIZE = 100

# Locks protecting concurrent access to caches and commit state
_schedule_cache_lock: asyncio.Lock = asyncio.Lock()
_image_cache_lock: asyncio.Lock = asyncio.Lock()
_commit_state_lock: asyncio.Lock = asyncio.Lock()
_queue_source_update_lock: asyncio.Lock = asyncio.Lock()

# Chart render mode: False = on_change (cache), True = on_demand (always re-render)
_chart_render_on_demand: bool = False


def set_chart_render_mode(on_demand: bool) -> None:
    """Update the in-memory chart render mode flag (persisted in DB by the caller)."""
    global _chart_render_on_demand
    _chart_render_on_demand = on_demand


def get_chart_render_on_demand() -> bool:
    return _chart_render_on_demand


def _normalize_check_unix(check_unix: int | None) -> int:
    """Return a safe unix timestamp for timestamp entities/chart metadata."""
    try:
        return int(check_unix) if check_unix is not None else int(time.time())
    except (TypeError, ValueError):
        return int(time.time())


def _normalize_dtek_updated_at(value: Any) -> str | None:
    """Normalize upstream timestamp into ``DD.MM.YYYY HH:MM`` Kyiv format."""
    if isinstance(value, datetime):
        return value.astimezone(KYIV_TZ).strftime("%d.%m.%Y %H:%M")

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value), tz=KYIV_TZ).strftime("%d.%m.%Y %H:%M")

    if not isinstance(value, str):
        return None

    raw = value.strip()
    if not raw:
        return None

    if raw.isdigit():
        try:
            return datetime.fromtimestamp(int(raw), tz=KYIV_TZ).strftime("%d.%m.%Y %H:%M")
        except (OverflowError, ValueError):
            return None

    known_formats = (
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
    )
    for fmt in known_formats:
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KYIV_TZ)
            return dt.astimezone(KYIV_TZ).strftime("%d.%m.%Y %H:%M")
        except ValueError:
            continue

    try:
        iso_candidate = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso_candidate)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KYIV_TZ)
        return dt.astimezone(KYIV_TZ).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return None


def normalize_schedule_chart_metadata(
    schedule_data: dict,
    check_unix: int | None = None,
) -> tuple[dict, int]:
    """Return chart metadata with guaranteed ``dtek_updated_at`` before rendering."""
    safe_unix = _normalize_check_unix(check_unix)
    normalized_data = dict(schedule_data)

    normalized_dt = _normalize_dtek_updated_at(schedule_data.get("dtek_updated_at"))
    if normalized_dt is None:
        normalized_dt = datetime.fromtimestamp(safe_unix, tz=KYIV_TZ).strftime("%d.%m.%Y %H:%M")

    normalized_data["dtek_updated_at"] = normalized_dt
    return normalized_data, safe_unix


def build_chart_fingerprint(schedule_data: dict | None = None, *, chart_version: int | None = None) -> str:
    """Return a stable cache fingerprint for chart images.

    The fingerprint includes:
    - normalized ``dtek_updated_at`` (header metadata shown on chart),
    - optional chart template version (``chart_cache.CHART_VERSION``),
    so cache keys rotate both on data timestamp changes and layout updates.
    """
    normalized_dt = _normalize_dtek_updated_at((schedule_data or {}).get("dtek_updated_at")) or "unknown"
    version_part = f"v{chart_version}" if chart_version is not None else "v?"
    raw = f"{version_part}:{normalized_dt}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


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
                raw = await resp.content.read(_MAX_COMMIT_RESPONSE + 1)
                if len(raw) > _MAX_COMMIT_RESPONSE:
                    logger.warning("GitHub commits response too large (%d bytes), skipping", len(raw))
                    return True, None
                commits = json.loads(raw)
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
                            logger.debug("No running event loop at initial SHA save; will persist on next update")
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
    """Fetch schedule JSON for *region*, with L1 in-memory caching and a circuit breaker.

    When the upstream source has been failing repeatedly the circuit breaker
    opens and we return stale cached data (if available) instead of hammering
    a down endpoint.
    """
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

    # If the circuit is OPEN (not half_open), return stale cache rather than failing hard.
    # HALF_OPEN must proceed to allow the circuit breaker probe call through.
    if _schedule_api_breaker.state == "open":
        async with _schedule_cache_lock:
            if cache_key in _schedule_cache:
                _, stale = _schedule_cache[cache_key]
                logger.warning(
                    "schedule_api circuit breaker open — returning stale cache for %s",
                    region,
                )
                return stale
        logger.warning(
            "schedule_api circuit breaker open — no cache available for %s",
            region,
        )
        return None

    url = settings.DATA_URL_TEMPLATE.replace('{region}', region)
    req_headers: dict[str, str] = {"User-Agent": "SvitloCheck-Bot/4.0"}
    if force_refresh:
        req_headers["Cache-Control"] = "no-cache, no-store"

    retry_delays = [1, 3]

    async def _do_fetch() -> dict | None:
        for attempt in range(len(retry_delays) + 1):
            _owned = False
            _session = _http_client
            if _session is None:
                logger.warning("HTTP client not initialised, falling back to temporary session")
                _session = aiohttp.ClientSession()
                _owned = True
            try:
                _t0 = time.monotonic()
                async with _session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=30),
                    headers=req_headers,
                ) as resp:
                    if resp.status == 200:
                        raw = await resp.content.read(_MAX_JSON_RESPONSE + 1)
                        if len(raw) > _MAX_JSON_RESPONSE:
                            logger.warning("Schedule response too large (%d bytes) for %s", len(raw), region)
                            return None
                        try:
                            fetched = json.loads(raw)
                        except json.JSONDecodeError as e:
                            logger.warning("Schedule fetch %s returned malformed JSON: %s", region, e)
                            SCHEDULE_FETCH_ERRORS.labels(region=region).inc()
                            return None
                        SCHEDULE_FETCH_DURATION.observe(time.monotonic() - _t0)
                        async with _schedule_cache_lock:
                            if len(_schedule_cache) >= MAX_CACHE_SIZE:
                                _schedule_cache.popitem(last=False)
                            _schedule_cache[cache_key] = (now, fetched)
                            _schedule_cache.move_to_end(cache_key)
                        return fetched
                    logger.warning("Schedule fetch %s returned %d", region, resp.status)
            except (TimeoutError, aiohttp.ClientError) as e:
                logger.warning("Schedule fetch %s attempt %d failed: %s", region, attempt + 1, e)
                if attempt == len(retry_delays):
                    SCHEDULE_FETCH_ERRORS.labels(region=region).inc()
                    raise  # re-raise last error so circuit breaker records the failure
            finally:
                if _owned:
                    await _session.close()
            if attempt < len(retry_delays):
                await asyncio.sleep(retry_delays[attempt])
        return None

    try:
        return await _schedule_api_breaker.call(_do_fetch)
    except CircuitBreakerOpen:
        async with _schedule_cache_lock:
            if cache_key in _schedule_cache:
                _, stale = _schedule_cache[cache_key]
                return stale
        return None
    except (TimeoutError, aiohttp.ClientError):
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


async def get_queue_source_updated_at(region: str, queue: str) -> str | None:
    """Return source update time for a region/queue based on upstream ``data``.

    For accuracy we read commit metadata for ``data/{region}.json`` from the
    source repository (rather than ``images/...`` pre-rendered assets).
    This reflects when the schedule data file for the region was last updated.

    ``queue`` is kept in the signature for call-site compatibility and logging.
    """
    path = f"data/{region}.json"
    now = datetime.now()

    async with _queue_source_update_lock:
        cached = _queue_source_update_cache.get(path)
        if cached and now - cached[0] < QUEUE_SOURCE_UPDATE_TTL:
            _queue_source_update_cache.move_to_end(path)
            return cached[1]
        cached_value: str | None = cached[1] if cached else None
        cached_etag = _queue_source_update_etags.get(path)

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Voltyk-Bot/4.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"
    if cached_etag:
        headers["If-None-Match"] = cached_etag

    url = "https://api.github.com/repos/Baskerville42/outage-data-ua/commits"
    params = {"per_page": "1", "path": path}

    _owned = False
    _session = _http_client
    if _session is None:
        _session = aiohttp.ClientSession()
        _owned = True
    try:
        async with _session.get(
            url,
            params=params,
            timeout=aiohttp.ClientTimeout(total=15),
            headers=headers,
        ) as resp:
            if resp.status == 304:
                async with _queue_source_update_lock:
                    _queue_source_update_cache[path] = (datetime.now(), cached_value)
                    _queue_source_update_cache.move_to_end(path)
                return cached_value

            if resp.status != 200:
                logger.warning(
                    "Queue source update API returned %d for %s/%s", resp.status, region, queue,
                )
                return cached_value

            new_etag = resp.headers.get("ETag")
            raw = await resp.content.read(_MAX_COMMIT_RESPONSE + 1)
            if len(raw) > _MAX_COMMIT_RESPONSE:
                logger.warning("Queue source commit response too large (%d bytes) for %s", len(raw), path)
                return cached_value

            commits = json.loads(raw)
            normalized: str | None = None
            if commits and isinstance(commits, list):
                first = commits[0] if commits else None
                commit = first.get("commit") if isinstance(first, dict) else None
                committer = commit.get("committer") if isinstance(commit, dict) else None
                author = commit.get("author") if isinstance(commit, dict) else None
                raw_ts = (
                    (committer or {}).get("date")
                    or (author or {}).get("date")
                )
                normalized = _normalize_dtek_updated_at(raw_ts)

            async with _queue_source_update_lock:
                _queue_source_update_cache[path] = (datetime.now(), normalized)
                _queue_source_update_cache.move_to_end(path)
                if len(_queue_source_update_cache) > MAX_CACHE_SIZE:
                    old_key, _ = _queue_source_update_cache.popitem(last=False)
                    _queue_source_update_etags.pop(old_key, None)
                if new_etag:
                    _queue_source_update_etags[path] = new_etag
            return normalized
    except Exception as e:
        logger.warning("Queue source update fetch failed for %s/%s: %s", region, queue, e)
        return cached_value
    finally:
        if _owned:
            await _session.close()


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
    chart_fingerprint: str | None = None
    if schedule_data is not None:
        source_updated_at = await get_queue_source_updated_at(region, queue)
        if source_updated_at:
            schedule_data = dict(schedule_data)
            schedule_data["dtek_updated_at"] = source_updated_at
        schedule_data, _ = normalize_schedule_chart_metadata(schedule_data)
        chart_fingerprint = build_chart_fingerprint(
            schedule_data,
            chart_version=chart_cache.CHART_VERSION,
        )

    if _chart_render_on_demand and schedule_data is not None:
        from bot.services.chart_generator import generate_schedule_chart
        return await generate_schedule_chart(region, queue, schedule_data)

    cache_key = f"{region}_{queue}_{chart_fingerprint}" if chart_fingerprint else f"{region}_{queue}"
    now = datetime.now()

    # ── L1: in-memory ─────────────────────────────────────────────────────────
    async with _image_cache_lock:
        if cache_key in _image_cache:
            cached_at, data = _image_cache[cache_key]
            if now - cached_at < CACHE_TTL:
                _image_cache.move_to_end(cache_key)
                return data

    # ── L2: Redis ─────────────────────────────────────────────────────────────
    redis_data = await chart_cache.get(region, queue, fingerprint=chart_fingerprint)
    if redis_data:
        await _l1_store_async(cache_key, now, redis_data)
        return redis_data

    # ── Generate locally ──────────────────────────────────────────────────────
    if schedule_data is not None:
        from bot.services.chart_generator import generate_schedule_chart
        generated = await generate_schedule_chart(region, queue, schedule_data)
        if generated:
            await chart_cache.store(region, queue, generated, fingerprint=chart_fingerprint)
            await _l1_store_async(cache_key, now, generated)
            return generated
        logger.warning("Local chart generation failed for %s/%s — falling back to GitHub", region, queue)

    # ── Fallback: GitHub pre-rendered PNG ─────────────────────────────────────
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
                headers={"User-Agent": "SvitloCheck-Bot/4.0"},
            ) as resp:
                if resp.status == 200:
                    data = await resp.content.read(_MAX_IMAGE_RESPONSE + 1)
                    if len(data) > _MAX_IMAGE_RESPONSE:
                        logger.warning("Image response too large (%d bytes) for %s/%s", len(data), region, queue)
                        return None
                    await chart_cache.store(region, queue, data, fingerprint=chart_fingerprint)
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
    """Parse raw API data into schedule events for a specific queue.

    Returns a dict with:
    - ``hasData``: ``True`` when at least one event was parsed.
    - ``events``: list of power-on/off windows.
    - ``queue``: queue label passed to the parser.
    - ``dtek_updated_at``: normalized upstream update timestamp in
      ``DD.MM.YYYY HH:MM`` (Kyiv time) or ``None`` when absent/invalid.
    """
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

    dtek_updated_at: str | None = _extract_dtek_updated_at(raw_data, fact)
    return {"hasData": len(events) > 0, "events": events, "queue": queue, "dtek_updated_at": dtek_updated_at}


def _extract_dtek_updated_at(raw_data: dict, fact: dict) -> str | None:
    """Extract and normalize update timestamp from known upstream payload variants."""
    candidate_keys = (
        "update",
        "updated",
        "updated_at",
        "updatedAt",
        "last_update",
        "lastUpdated",
        "last_updated_at",
        "generated_at",
        "generatedAt",
        "timestamp",
        "ts",
    )
    nested_containers = (
        "meta",
        "metadata",
        "info",
        "header",
        "source",
        "mirror",
        "attrs",
        "timestamps",
        "payload",
        "result",
    )

    def _iter_candidates(container: dict, root_name: str) -> list[tuple[str, Any]]:
        out: list[tuple[str, Any]] = []
        for key in candidate_keys:
            if key in container:
                out.append((f"{root_name}.{key}", container.get(key)))

        for nested in nested_containers:
            nested_value = container.get(nested)
            if not isinstance(nested_value, dict):
                continue
            for key in candidate_keys:
                if key in nested_value:
                    out.append((f"{root_name}.{nested}.{key}", nested_value.get(key)))
        return out

    for source, candidate in _iter_candidates(fact, "fact") + _iter_candidates(raw_data, "raw"):
        normalized = _normalize_dtek_updated_at(candidate)
        if normalized is not None:
            return normalized
        if candidate not in (None, ""):
            logger.warning("Ignoring invalid dtek_updated_at candidate from %s: %r", source, candidate)

    return None


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
