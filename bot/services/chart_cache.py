"""Redis-backed persistent storage for pre-rendered schedule chart images.

Two-level caching strategy
──────────────────────────
L1  in-memory OrderedDict  (2 min TTL, max 100 entries) — inside api.py
L2  Redis                  (25 h TTL)                   — this module

Lookup order: L1 → L2 → generate → store both → return
Pre-render:   on schedule change → delete L2 → generate → store L2
              (L1 is cleared by invalidate_image_cache in api.py)

This guarantees that each chart is generated at most once per schedule
update, and every subsequent request — whether from a notification blast
or from a user tapping the "Графік" button — is served from cache.
"""
from __future__ import annotations

import redis.asyncio as aioredis

from bot.config import settings
from bot.utils.logger import get_logger

logger = get_logger(__name__)

# 25 h — survives overnight; fresh data is always written when schedule changes
CHART_TTL_S: int = 60 * 60 * 25

# Bump this when the chart layout/design changes so old cached images are
# automatically bypassed without needing a manual Redis flush.
CHART_VERSION: int = 7

_redis: aioredis.Redis | None = None


# ── Lifecycle ─────────────────────────────────────────────────────────────────

async def init() -> None:
    """Create the Redis client. Call once at bot startup."""
    global _redis
    _redis = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=False,   # we store raw bytes
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    # Verify connectivity
    try:
        await _redis.ping()
        logger.info("✅ Chart cache Redis client ініційований (%s)", settings.REDIS_URL.split("@")[-1])
    except Exception as e:
        logger.warning("Chart cache Redis ping failed (will retry on use): %s", e)


async def close() -> None:
    """Close the Redis client. Call once at bot shutdown."""
    global _redis
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception:
            pass
        _redis = None


# ── Key helpers ───────────────────────────────────────────────────────────────

def _key(region: str, queue: str) -> str:
    return f"chart:v{CHART_VERSION}:{region}:{queue}"


# ── Public API ────────────────────────────────────────────────────────────────

def is_usable() -> bool:
    """Return True when the Redis client has been initialised successfully."""
    return _redis is not None


async def get(region: str, queue: str) -> bytes | None:
    """Return the cached PNG bytes, or None if not found / Redis unavailable."""
    if _redis is None:
        return None
    try:
        return await _redis.get(_key(region, queue))
    except Exception as e:
        logger.warning("chart_cache.get %s/%s failed: %s", region, queue, e)
        return None


async def store(region: str, queue: str, data: bytes) -> None:
    """Persist PNG bytes in Redis with the standard TTL."""
    if _redis is None:
        return
    try:
        await _redis.setex(_key(region, queue), CHART_TTL_S, data)
        logger.debug(
            "chart_cache: stored %s/%s (%d KB, TTL %dh)",
            region, queue, len(data) // 1024, CHART_TTL_S // 3600,
        )
    except Exception as e:
        logger.warning("chart_cache.store %s/%s failed: %s", region, queue, e)


async def delete(region: str, queue: str) -> None:
    """Remove the cached chart so the next request triggers a fresh render."""
    if _redis is None:
        return
    try:
        await _redis.delete(_key(region, queue))
        logger.debug("chart_cache: deleted %s/%s", region, queue)
    except Exception as e:
        logger.warning("chart_cache.delete %s/%s failed: %s", region, queue, e)
