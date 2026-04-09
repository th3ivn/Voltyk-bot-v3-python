"""Tests for bot/services/api.py — HTTP-dependent functions and cache operations.

Covers the previously untested 61%:
- set_chart_render_mode / get_chart_render_on_demand
- fetch_schedule_data: cache hit, 200, non-200, retry-then-fail, force_refresh
- check_source_repo_updated: initial run, 304, new SHA, same SHA, network error
- invalidate_image_cache / _l1_store_async
- parse_schedule_for_queue: tomorrow's data path
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from aioresponses import aioresponses

KYIV_TZ = ZoneInfo("Europe/Kyiv")
GITHUB_COMMITS_URL = (
    "https://api.github.com/repos/Baskerville42/outage-data-ua/commits"
    "?per_page=1&path=data"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_api_state() -> None:
    """Reset all module-level cache/state between tests."""
    import bot.services.api as api

    api._schedule_cache.clear()
    api._image_cache.clear()
    api._last_commit_sha = None
    api._last_etag = None
    api._http_client = None
    api._chart_render_on_demand = False


def _make_raw_schedule(queue: str = "1.1") -> dict:
    """Minimal raw schedule payload for *queue*."""
    now = datetime.now(KYIV_TZ)
    ts = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    return {
        "fact": {
            "data": {
                str(ts): {
                    f"GPV{queue}": {"14": "no"},
                }
            }
        }
    }


# ---------------------------------------------------------------------------
# set_chart_render_mode / get_chart_render_on_demand
# ---------------------------------------------------------------------------


class TestChartRenderMode:
    def setup_method(self):
        _reset_api_state()

    def test_defaults_to_false(self):
        from bot.services.api import get_chart_render_on_demand

        assert get_chart_render_on_demand() is False

    def test_set_true(self):
        from bot.services.api import get_chart_render_on_demand, set_chart_render_mode

        set_chart_render_mode(True)
        assert get_chart_render_on_demand() is True

    def test_set_false_after_true(self):
        from bot.services.api import get_chart_render_on_demand, set_chart_render_mode

        set_chart_render_mode(True)
        set_chart_render_mode(False)
        assert get_chart_render_on_demand() is False


# ---------------------------------------------------------------------------
# fetch_schedule_data
# ---------------------------------------------------------------------------


class TestFetchScheduleData:
    def setup_method(self):
        _reset_api_state()

    async def test_successful_fetch_returns_data(self):
        from bot.services.api import fetch_schedule_data

        payload = _make_raw_schedule()
        url = "https://example.com/kyiv.json"

        with (
            patch("bot.services.api.settings") as mock_settings,
            aioresponses() as m,
        ):
            mock_settings.DATA_URL_TEMPLATE = "https://example.com/{region}.json"
            mock_settings.SCHEDULE_CHECK_INTERVAL_S = 60
            mock_settings.GITHUB_TOKEN = ""
            m.get(url, payload=payload, status=200)
            result = await fetch_schedule_data("kyiv")

        assert result is not None
        assert "fact" in result

    async def test_cache_hit_returns_cached_data(self):
        """Second call within TTL should not make an HTTP request."""
        from bot.services.api import fetch_schedule_data

        payload = _make_raw_schedule()
        url = "https://example.com/kyiv.json"

        with (
            patch("bot.services.api.settings") as mock_settings,
            aioresponses() as m,
        ):
            mock_settings.DATA_URL_TEMPLATE = "https://example.com/{region}.json"
            mock_settings.SCHEDULE_CHECK_INTERVAL_S = 60
            mock_settings.GITHUB_TOKEN = ""
            m.get(url, payload=payload, status=200)
            # First call — hits HTTP
            first = await fetch_schedule_data("kyiv")
            # Second call — should come from cache (no extra m.get needed)
            second = await fetch_schedule_data("kyiv")

        assert first == second

    async def test_non_200_response_returns_none(self):
        from bot.services.api import fetch_schedule_data

        url = "https://example.com/kyiv.json"

        with (
            patch("bot.services.api.settings") as mock_settings,
            patch("bot.services.api.asyncio.sleep", AsyncMock()),
            aioresponses() as m,
        ):
            mock_settings.DATA_URL_TEMPLATE = "https://example.com/{region}.json"
            mock_settings.SCHEDULE_CHECK_INTERVAL_S = 60
            mock_settings.GITHUB_TOKEN = ""
            # All 3 attempts return 503
            for _ in range(3):
                m.get(url, status=503)
            result = await fetch_schedule_data("kyiv")

        assert result is None

    async def test_force_refresh_bypasses_cache(self):
        """force_refresh=True skips the cache even if data is fresh."""
        import bot.services.api as api_mod
        from bot.services.api import fetch_schedule_data

        payload1 = _make_raw_schedule()
        payload2 = {"fact": {"data": {}, "updated": "02.01.2024 10:00"}}
        # force_refresh pins URL to commit SHA: /main/ → /{sha}/
        sha_url = "https://example.com/abc123/data/kyiv.json"

        old_sha = api_mod._last_commit_sha
        old_fresh = api_mod._commit_sha_fresh
        try:
            api_mod._last_commit_sha = "abc123"
            api_mod._commit_sha_fresh = True
            with (
                patch("bot.services.api.settings") as mock_settings,
                aioresponses() as m,
            ):
                mock_settings.DATA_URL_TEMPLATE = "https://example.com/main/data/{region}.json"
                mock_settings.SCHEDULE_CHECK_INTERVAL_S = 60
                mock_settings.GITHUB_TOKEN = ""
                m.get("https://example.com/main/data/kyiv.json", payload=payload1, status=200)
                await fetch_schedule_data("kyiv")

                # Second fetch with force_refresh — URL pinned to SHA
                m.get(sha_url, payload=payload2, status=200)
                result = await fetch_schedule_data("kyiv", force_refresh=True)

            assert result == payload2
        finally:
            api_mod._last_commit_sha = old_sha
            api_mod._commit_sha_fresh = old_fresh

    async def test_network_error_then_success_on_retry(self):
        """First attempt raises ClientError; second attempt succeeds."""
        import aiohttp
        from bot.services.api import fetch_schedule_data

        payload = _make_raw_schedule()
        url = "https://example.com/kyiv.json"

        with (
            patch("bot.services.api.settings") as mock_settings,
            patch("bot.services.api.asyncio.sleep", AsyncMock()),
            aioresponses() as m,
        ):
            mock_settings.DATA_URL_TEMPLATE = "https://example.com/{region}.json"
            mock_settings.SCHEDULE_CHECK_INTERVAL_S = 60
            mock_settings.GITHUB_TOKEN = ""
            m.get(url, exception=aiohttp.ClientError("timeout"))
            m.get(url, payload=payload, status=200)
            result = await fetch_schedule_data("kyiv")

        assert result is not None


# ---------------------------------------------------------------------------
# check_source_repo_updated
# ---------------------------------------------------------------------------


class TestCheckSourceRepoUpdated:
    def setup_method(self):
        _reset_api_state()

    async def test_initial_run_no_sha_returns_true(self):
        """First call (no stored SHA) → returns (True, None)."""
        from bot.services.api import check_source_repo_updated

        commits = [{"sha": "abc123def456" + "0" * 28}]

        with (
            patch("bot.services.api.settings") as mock_settings,
            patch("bot.services.api.asyncio.get_running_loop") as mock_loop,
            aioresponses() as m,
        ):
            mock_settings.GITHUB_TOKEN = ""
            # close() the coroutine to avoid "coroutine never awaited" warning
            mock_loop.return_value.create_task = lambda coro, **kw: coro.close()
            m.get(GITHUB_COMMITS_URL, payload=commits, status=200)
            has_update, sha = await check_source_repo_updated()

        assert has_update is True
        assert sha is None  # first run always returns None for sha

    async def test_304_not_modified_returns_false(self):
        """ETag cached → GitHub 304 → (False, None)."""
        import bot.services.api as api
        from bot.services.api import check_source_repo_updated

        api._last_commit_sha = "existing_sha"
        api._last_etag = '"some-etag"'

        with (
            patch("bot.services.api.settings") as mock_settings,
            aioresponses() as m,
        ):
            mock_settings.GITHUB_TOKEN = ""
            m.get(GITHUB_COMMITS_URL, status=304)
            has_update, sha = await check_source_repo_updated()

        assert has_update is False
        assert sha is None

    async def test_new_commit_returns_true_with_sha(self):
        """Stored SHA differs from API response → (True, new_sha)."""
        import bot.services.api as api
        from bot.services.api import check_source_repo_updated

        old_sha = "a" * 40
        new_sha = "b" * 40
        api._last_commit_sha = old_sha

        with (
            patch("bot.services.api.settings") as mock_settings,
            patch("bot.services.api.asyncio.get_running_loop") as mock_loop,
            aioresponses() as m,
        ):
            mock_settings.GITHUB_TOKEN = ""
            # close() the coroutine to avoid "coroutine never awaited" warning
            mock_loop.return_value.create_task = lambda coro, **kw: coro.close()
            m.get(GITHUB_COMMITS_URL, payload=[{"sha": new_sha}], status=200)
            has_update, sha = await check_source_repo_updated()

        assert has_update is True
        assert sha == new_sha

    async def test_same_sha_returns_false(self):
        """Stored SHA equals API response → (False, None)."""
        import bot.services.api as api
        from bot.services.api import check_source_repo_updated

        existing_sha = "c" * 40
        api._last_commit_sha = existing_sha

        with (
            patch("bot.services.api.settings") as mock_settings,
            aioresponses() as m,
        ):
            mock_settings.GITHUB_TOKEN = ""
            m.get(GITHUB_COMMITS_URL, payload=[{"sha": existing_sha}], status=200)
            has_update, sha = await check_source_repo_updated()

        assert has_update is False
        assert sha is None

    async def test_network_error_returns_true_failsafe(self):
        """Exception → fail-safe (True, None) so callers always do a full check."""
        import aiohttp
        from bot.services.api import check_source_repo_updated

        with (
            patch("bot.services.api.settings") as mock_settings,
            aioresponses() as m,
        ):
            mock_settings.GITHUB_TOKEN = ""
            m.get(GITHUB_COMMITS_URL, exception=aiohttp.ClientError("conn reset"))
            has_update, sha = await check_source_repo_updated()

        assert has_update is True
        assert sha is None

    async def test_non_200_non_304_returns_true_failsafe(self):
        """5xx response → (True, None)."""
        from bot.services.api import check_source_repo_updated

        with (
            patch("bot.services.api.settings") as mock_settings,
            aioresponses() as m,
        ):
            mock_settings.GITHUB_TOKEN = ""
            m.get(GITHUB_COMMITS_URL, status=500)
            has_update, sha = await check_source_repo_updated()

        assert has_update is True
        assert sha is None

    async def test_unexpected_commit_structure_returns_true(self):
        """Commit object without 'sha' key → (True, None)."""
        from bot.services.api import check_source_repo_updated

        with (
            patch("bot.services.api.settings") as mock_settings,
            aioresponses() as m,
        ):
            mock_settings.GITHUB_TOKEN = ""
            m.get(GITHUB_COMMITS_URL, payload=[{"no_sha_here": True}], status=200)
            has_update, sha = await check_source_repo_updated()

        assert has_update is True
        assert sha is None

    async def test_empty_commits_list_returns_true(self):
        """Empty list body → (True, None)."""
        from bot.services.api import check_source_repo_updated

        with (
            patch("bot.services.api.settings") as mock_settings,
            aioresponses() as m,
        ):
            mock_settings.GITHUB_TOKEN = ""
            m.get(GITHUB_COMMITS_URL, payload=[], status=200)
            has_update, sha = await check_source_repo_updated()

        assert has_update is True
        assert sha is None


# ---------------------------------------------------------------------------
# invalidate_image_cache / _l1_store_async
# ---------------------------------------------------------------------------


class TestImageCacheOps:
    def setup_method(self):
        _reset_api_state()

    async def test_invalidate_removes_existing_entry(self):
        import bot.services.api as api
        from bot.services.api import invalidate_image_cache

        # Pre-populate L1 cache — key format is f"{region}_{queue}" (dot preserved)
        api._image_cache["kyiv_1.1"] = (datetime.now(), b"fake_png")
        await invalidate_image_cache("kyiv", "1.1")

        assert "kyiv_1.1" not in api._image_cache

    async def test_invalidate_nonexistent_key_is_noop(self):
        from bot.services.api import invalidate_image_cache

        # Should not raise
        await invalidate_image_cache("nonexistent", "9.9")

    async def test_l1_store_writes_to_cache(self):
        import bot.services.api as api
        from bot.services.api import _l1_store_async

        now = datetime.now()
        data = b"chart_data"
        await _l1_store_async("kyiv_1-1", now, data)

        assert "kyiv_1-1" in api._image_cache
        cached_at, cached_data = api._image_cache["kyiv_1-1"]
        assert cached_data == data

    async def test_l1_store_evicts_oldest_when_full(self):
        """When cache reaches MAX_CACHE_SIZE, oldest entry is evicted."""
        import bot.services.api as api
        from bot.services.api import _l1_store_async

        # Fill cache to capacity
        now = datetime.now()
        for i in range(api.MAX_CACHE_SIZE):
            api._image_cache[f"key_{i}"] = (now, b"data")

        # Add one more → should evict the first (LRU)
        await _l1_store_async("new_key", now, b"new_data")

        assert len(api._image_cache) == api.MAX_CACHE_SIZE
        assert "new_key" in api._image_cache
        assert "key_0" not in api._image_cache


# ---------------------------------------------------------------------------
# parse_schedule_for_queue — tomorrow's data path
# ---------------------------------------------------------------------------


class TestParseScheduleForQueueTomorrow:
    """Tests the tomorrow_ts branch that was uncovered (lines 452-469)."""

    def _make_raw_two_days(self, queue: str = "1.1") -> dict:
        from datetime import timedelta

        now = datetime.now(KYIV_TZ)
        today_ts = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        tomorrow_ts = today_ts + 86400
        queue_key = f"GPV{queue}"
        return {
            "fact": {
                "update": "07.04.2026 06:00",
                "data": {
                    str(today_ts): {queue_key: {"14": "no"}},
                    str(tomorrow_ts): {queue_key: {"10": "no"}},
                },
            }
        }

    def test_includes_tomorrow_events(self):
        from bot.services.api import parse_schedule_for_queue

        raw = self._make_raw_two_days()
        result = parse_schedule_for_queue(raw, "1.1")

        assert result["hasData"] is True
        # Should have events from both today AND tomorrow
        assert len(result["events"]) >= 2

    def test_dtek_updated_at_extracted(self):
        from bot.services.api import parse_schedule_for_queue

        raw = self._make_raw_two_days()
        result = parse_schedule_for_queue(raw, "1.1")
        assert result.get("dtek_updated_at") == "07.04.2026 06:00"

    def test_tomorrow_possible_events_included(self):
        from bot.services.api import parse_schedule_for_queue

        now = datetime.now(KYIV_TZ)
        today_ts = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        tomorrow_ts = today_ts + 86400
        raw = {
            "fact": {
                "data": {
                    str(today_ts): {"GPV1.1": {}},
                    str(tomorrow_ts): {"GPV1.1": {"12": "maybe"}},
                }
            }
        }
        result = parse_schedule_for_queue(raw, "1.1")
        assert any(ev["isPossible"] for ev in result["events"])


# ---------------------------------------------------------------------------
# HTTP client lifecycle
# ---------------------------------------------------------------------------


class TestHttpClientLifecycle:
    def setup_method(self):
        _reset_api_state()

    async def test_init_creates_client(self):
        import bot.services.api as api
        from bot.services.api import init_http_client

        await init_http_client()
        assert api._http_client is not None
        await api._http_client.close()
        api._http_client = None

    async def test_close_resets_client_to_none(self):
        import bot.services.api as api
        from bot.services.api import close_http_client, init_http_client

        await init_http_client()
        await close_http_client()
        assert api._http_client is None

    async def test_close_when_none_is_noop(self):
        from bot.services.api import close_http_client

        # Should not raise
        await close_http_client()
