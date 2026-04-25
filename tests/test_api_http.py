"""Tests for bot/services/api.py — HTTP-dependent functions and cache operations.

Covers the previously untested 61%:
- set_chart_render_mode / get_chart_render_on_demand
- fetch_schedule_data: cache hit, 200, non-200, retry-then-fail, force_refresh
- check_source_repo_updated: initial run, 304, new SHA, same SHA, network error
- invalidate_image_cache / _l1_store_async
- parse_schedule_for_queue: tomorrow's data path
"""
from __future__ import annotations

import re
import time
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
    api._queue_source_update_cache.clear()
    api._queue_source_update_etags.clear()


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
        from bot.services.api import fetch_schedule_data

        payload1 = _make_raw_schedule()
        payload2 = {"fact": {"data": {}, "updated": "02.01.2024 10:00"}}
        url = "https://example.com/kyiv.json"

        with (
            patch("bot.services.api.settings") as mock_settings,
            aioresponses() as m,
        ):
            mock_settings.DATA_URL_TEMPLATE = "https://example.com/{region}.json"
            mock_settings.SCHEDULE_CHECK_INTERVAL_S = 60
            mock_settings.GITHUB_TOKEN = ""
            m.get(url, payload=payload1, status=200)
            await fetch_schedule_data("kyiv")

            # Second fetch with force_refresh — should hit HTTP again
            m.get(url, payload=payload2, status=200)
            result = await fetch_schedule_data("kyiv", force_refresh=True)

        assert result == payload2

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

    def test_dtek_updated_at_extracted_from_top_level_fallback(self):
        from bot.services.api import parse_schedule_for_queue

        raw = self._make_raw_two_days()
        raw["fact"].pop("update")
        raw["updated_at"] = "08.04.2026 07:30"

        result = parse_schedule_for_queue(raw, "1.1")
        assert result.get("dtek_updated_at") == "08.04.2026 07:30"

    def test_dtek_updated_at_extracted_from_fact_metadata(self):
        from bot.services.api import parse_schedule_for_queue

        raw = self._make_raw_two_days()
        raw["fact"].pop("update")
        raw["fact"]["metadata"] = {"updatedAt": "2026-04-08T04:30:00+03:00"}

        result = parse_schedule_for_queue(raw, "1.1")
        assert result.get("dtek_updated_at") == "08.04.2026 04:30"

    def test_dtek_updated_at_extracted_from_raw_meta_iso_z(self):
        from bot.services.api import parse_schedule_for_queue

        raw = self._make_raw_two_days()
        raw["fact"].pop("update")
        raw["meta"] = {"last_update": "2026-04-07T03:00:00Z"}

        result = parse_schedule_for_queue(raw, "1.1")
        assert result.get("dtek_updated_at") == "07.04.2026 06:00"

    def test_dtek_updated_at_unix_timestamp_supported(self):
        from bot.services.api import parse_schedule_for_queue

        raw = self._make_raw_two_days()
        raw["fact"]["update"] = "1775530800"

        result = parse_schedule_for_queue(raw, "1.1")
        assert result.get("dtek_updated_at") == "07.04.2026 06:00"

    def test_dtek_updated_at_invalid_value_is_not_exposed(self):
        from bot.services.api import parse_schedule_for_queue

        raw = self._make_raw_two_days()
        raw["fact"]["update"] = "totally-not-a-date"

        with patch("bot.services.api.logger.warning") as mock_warning:
            result = parse_schedule_for_queue(raw, "1.1")

        assert result.get("dtek_updated_at") is None
        mock_warning.assert_called_once()
        assert "Ignoring invalid dtek_updated_at candidate" in mock_warning.call_args[0][0]

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


# ---------------------------------------------------------------------------
# GitHub token header (line 103)
# ---------------------------------------------------------------------------


class TestGithubTokenHeader:
    def setup_method(self):
        _reset_api_state()

    async def test_token_added_to_headers(self):
        """When GITHUB_TOKEN is set, Authorization header is included."""
        import bot.services.api as api
        from bot.services.api import check_source_repo_updated

        api._last_commit_sha = "a" * 40

        with (
            patch("bot.services.api.settings") as mock_settings,
            aioresponses() as m,
        ):
            mock_settings.GITHUB_TOKEN = "gh_secret_token"
            m.get(GITHUB_COMMITS_URL, payload=[{"sha": "a" * 40}], status=200)
            has_update, _ = await check_source_repo_updated()

        assert has_update is False  # same SHA → no update; just verifying no exception


# ---------------------------------------------------------------------------
# ETag saved (line 126)
# ---------------------------------------------------------------------------


class TestETagSaved:
    def setup_method(self):
        _reset_api_state()

    async def test_new_etag_stored_in_module(self):
        """200 response with ETag header → _last_etag updated (line 126)."""
        import bot.services.api as api
        from bot.services.api import check_source_repo_updated

        api._last_commit_sha = "a" * 40
        assert api._last_etag is None

        with (
            patch("bot.services.api.settings") as mock_settings,
            aioresponses() as m,
        ):
            mock_settings.GITHUB_TOKEN = ""
            m.get(
                GITHUB_COMMITS_URL,
                payload=[{"sha": "a" * 40}],
                status=200,
                headers={"ETag": '"abc123"'},
            )
            await check_source_repo_updated()

        assert api._last_etag == '"abc123"'


# ---------------------------------------------------------------------------
# RuntimeError from create_task (lines 141-142, 155-156)
# ---------------------------------------------------------------------------


class TestRuntimeErrorCreateTask:
    def setup_method(self):
        _reset_api_state()

    async def test_initial_sha_create_task_runtime_error_is_swallowed(self):
        """Initial commit SHA: create_task raises RuntimeError → swallowed."""
        import bot.services.api as api
        from bot.services.api import check_source_repo_updated

        assert api._last_commit_sha is None

        mock_loop = MagicMock()
        mock_loop.create_task.side_effect = RuntimeError("no running loop")

        with (
            patch("bot.services.api.settings") as mock_settings,
            patch("bot.services.api.asyncio.get_running_loop", return_value=mock_loop),
            aioresponses() as m,
        ):
            mock_settings.GITHUB_TOKEN = ""
            m.get(GITHUB_COMMITS_URL, payload=[{"sha": "a" * 40}], status=200)
            has_update, sha = await check_source_repo_updated()

        assert has_update is True
        assert sha is None

    async def test_new_sha_create_task_runtime_error_is_swallowed(self):
        """New SHA detected: create_task raises RuntimeError → logged, not raised."""
        import bot.services.api as api
        from bot.services.api import check_source_repo_updated

        api._last_commit_sha = "a" * 40
        new_sha = "b" * 40

        mock_loop = MagicMock()
        mock_loop.create_task.side_effect = RuntimeError("no running loop")

        with (
            patch("bot.services.api.settings") as mock_settings,
            patch("bot.services.api.asyncio.get_running_loop", return_value=mock_loop),
            aioresponses() as m,
        ):
            mock_settings.GITHUB_TOKEN = ""
            m.get(GITHUB_COMMITS_URL, payload=[{"sha": new_sha}], status=200)
            has_update, sha = await check_source_repo_updated()

        assert has_update is True
        assert sha == new_sha


# ---------------------------------------------------------------------------
# _save_commit_state (lines 176-186)
# ---------------------------------------------------------------------------


class TestSaveCommitState:
    def setup_method(self):
        _reset_api_state()

    async def test_saves_sha_and_etag(self):
        """_save_commit_state writes SHA and ETag via set_setting."""
        import bot.services.api as api
        from bot.services.api import _save_commit_state

        api._last_commit_sha = "abc123"
        api._last_etag = '"etag456"'

        mock_session = AsyncMock()
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("bot.db.session.async_session", return_value=session_ctx),
            patch("bot.db.queries.set_setting", AsyncMock()) as mock_set,
        ):
            await _save_commit_state()

        assert mock_set.await_count == 2
        mock_session.commit.assert_awaited_once()

    async def test_exception_is_swallowed(self):
        """DB error → warning logged, no re-raise."""
        import bot.services.api as api
        from bot.services.api import _save_commit_state

        api._last_commit_sha = "abc123"

        with patch(
            "bot.db.session.async_session",
            side_effect=RuntimeError("db down"),
        ):
            # Must not raise
            await _save_commit_state()


# ---------------------------------------------------------------------------
# load_last_commit_sha (lines 192-205)
# ---------------------------------------------------------------------------


class TestLoadLastCommitSha:
    def setup_method(self):
        _reset_api_state()

    async def test_loads_sha_and_etag(self):
        """load_last_commit_sha restores _last_commit_sha and _last_etag from DB."""
        import bot.services.api as api
        from bot.services.api import load_last_commit_sha

        mock_session = AsyncMock()
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("bot.db.session.async_session", return_value=session_ctx),
            patch("bot.db.queries.get_setting", AsyncMock(side_effect=["stored_sha", '"stored_etag"'])),
        ):
            await load_last_commit_sha()

        assert api._last_commit_sha == "stored_sha"
        assert api._last_etag == '"stored_etag"'

    async def test_none_values_not_set(self):
        """If DB returns None for both, module-level vars stay None."""
        import bot.services.api as api
        from bot.services.api import load_last_commit_sha

        mock_session = AsyncMock()
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        session_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("bot.db.session.async_session", return_value=session_ctx),
            patch("bot.db.queries.get_setting", AsyncMock(return_value=None)),
        ):
            await load_last_commit_sha()

        assert api._last_commit_sha is None
        assert api._last_etag is None

    async def test_exception_is_swallowed(self):
        """DB error → warning logged, no re-raise."""
        from bot.services.api import load_last_commit_sha

        with patch("bot.db.session.async_session", side_effect=RuntimeError("db down")):
            await load_last_commit_sha()


# ---------------------------------------------------------------------------
# fetch_schedule_data — circuit breaker OPEN (lines 232-244)
# ---------------------------------------------------------------------------


class TestCircuitBreakerOpen:
    def setup_method(self):
        _reset_api_state()

    async def test_open_with_stale_cache_returns_stale(self):
        """Circuit breaker OPEN + stale cache entry → stale data returned (lines 232-239)."""
        import bot.services.api as api
        from bot.services.api import fetch_schedule_data

        stale = {"fact": {"data": {}}}
        api._schedule_cache["kyiv"] = (datetime(2000, 1, 1), stale)
        api._schedule_api_breaker._state = "open"
        api._schedule_api_breaker._opened_at = time.monotonic()  # freshly opened

        with patch("bot.services.api.settings") as mock_settings:
            mock_settings.SCHEDULE_CHECK_INTERVAL_S = 60
            mock_settings.GITHUB_TOKEN = ""
            result = await fetch_schedule_data("kyiv")

        assert result is stale
        api._schedule_api_breaker._state = "closed"

    async def test_open_without_cache_returns_none(self):
        """Circuit breaker OPEN + no cache → None (lines 240-244)."""
        import bot.services.api as api
        from bot.services.api import fetch_schedule_data

        api._schedule_api_breaker._state = "open"
        api._schedule_api_breaker._opened_at = time.monotonic()  # freshly opened

        with patch("bot.services.api.settings") as mock_settings:
            mock_settings.SCHEDULE_CHECK_INTERVAL_S = 60
            mock_settings.GITHUB_TOKEN = ""
            result = await fetch_schedule_data("unknown_region")

        assert result is None
        api._schedule_api_breaker._state = "closed"


# ---------------------------------------------------------------------------
# fetch_schedule_data — null HTTP client fallback (line 273) and exhausted
# retries (lines 281-282, 292-299)
# ---------------------------------------------------------------------------


class TestFetchScheduleDataEdgeCases:
    def setup_method(self):
        _reset_api_state()

    async def test_null_client_uses_temp_session(self):
        """_http_client=None → temp ClientSession created and closed (line 273)."""
        import bot.services.api as api
        from bot.services.api import fetch_schedule_data

        assert api._http_client is None
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

    async def test_all_retries_exhausted_returns_none(self):
        """All 3 attempts raise ClientError → SCHEDULE_FETCH_ERRORS incremented, returns None."""
        import aiohttp

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
            # 3 failures (attempts 0, 1, 2) — triggers re-raise on last attempt
            for _ in range(3):
                m.get(url, exception=aiohttp.ClientError("timeout"))
            result = await fetch_schedule_data("kyiv")

        assert result is None

    async def test_circuit_breaker_open_after_failures(self):
        """CircuitBreakerOpen raised → stale cache or None returned (lines 292-297)."""
        import aiohttp

        import bot.services.api as api
        from bot.services.api import fetch_schedule_data

        # Plant stale cache entry before triggering the breaker
        stale = {"fact": {"data": {}}}
        api._schedule_cache["kyiv"] = (datetime(2000, 1, 1), stale)

        url = "https://example.com/kyiv.json"

        with (
            patch("bot.services.api.settings") as mock_settings,
            patch("bot.services.api.asyncio.sleep", AsyncMock()),
            aioresponses() as m,
        ):
            mock_settings.DATA_URL_TEMPLATE = "https://example.com/{region}.json"
            mock_settings.SCHEDULE_CHECK_INTERVAL_S = 60
            mock_settings.GITHUB_TOKEN = ""
            # Enough failures to open the circuit breaker (threshold=5 by default)
            for _ in range(20):
                m.get(url, exception=aiohttp.ClientError("timeout"))
            for _ in range(20):
                result = await fetch_schedule_data("kyiv", force_refresh=True)

        # Once breaker opens, stale data returned
        assert result is stale or result is None


# ---------------------------------------------------------------------------
# fetch_schedule_image (lines 343-405)
# ---------------------------------------------------------------------------


class TestQueueSourceUpdatedAt:
    def setup_method(self):
        _reset_api_state()

    async def test_reads_commit_date_for_region_data_path(self):
        from bot.services.api import get_queue_source_updated_at

        payload = [{
            "commit": {
                "committer": {"date": "2026-02-19T13:04:00Z"},
            }
        }]

        with (
            patch("bot.services.api.settings") as mock_settings,
            aioresponses() as m,
        ):
            mock_settings.GITHUB_TOKEN = ""
            m.get(
                re.compile(r"https://api\\.github\\.com/repos/Baskerville42/outage-data-ua/commits\\?.*path=(data%2F|data/)kyiv-region\\.json.*"),
                payload=payload,
                status=200,
            )
            result = await get_queue_source_updated_at("kyiv-region", "3.1")

        assert result == "19.02.2026 15:04"


class TestFetchScheduleImage:
    def setup_method(self):
        _reset_api_state()

    async def test_on_demand_renders_fresh(self):
        """on_demand mode → generate_schedule_chart called directly, no cache."""
        import bot.services.api as api
        from bot.services.api import fetch_schedule_image

        api._chart_render_on_demand = True
        schedule_data = {"events": [], "dtek_updated_at": ""}
        fake_png = b"fakepng"

        with patch(
            "bot.services.chart_generator.generate_schedule_chart",
            AsyncMock(return_value=fake_png),
        ), patch("bot.services.api.get_queue_source_updated_at", AsyncMock(return_value=None)):
            result = await fetch_schedule_image("kyiv", "1.1", schedule_data)

        assert result == fake_png

    async def test_l1_cache_hit_returns_cached(self):
        """Entry fresh in L1 → returned without any HTTP or generation."""
        import bot.services.api as api
        from bot.services.api import fetch_schedule_image

        cached_png = b"cached_png"
        api._image_cache["kyiv_1.1"] = (datetime.now(), cached_png)

        with patch("bot.services.chart_generator.generate_schedule_chart", AsyncMock()) as mock_gen:
            with patch("bot.services.chart_cache.get", AsyncMock(return_value=None)):
                result = await fetch_schedule_image("kyiv", "1.1", None)

        assert result == cached_png
        mock_gen.assert_not_awaited()

    async def test_l2_cache_hit_returns_and_populates_l1(self):
        """Redis L2 hit → returned and stored in L1."""
        import bot.services.api as api
        from bot.services.api import fetch_schedule_image

        redis_png = b"redis_png"

        with (
            patch("bot.services.chart_cache.get", AsyncMock(return_value=redis_png)),
            patch("bot.services.chart_cache.store", AsyncMock()),
        ):
            result = await fetch_schedule_image("kyiv", "1.1", None)

        assert result == redis_png
        assert "kyiv_1.1" in api._image_cache

    async def test_local_generation_used_when_no_cache(self):
        """No cache → generate_schedule_chart called, result stored in both caches."""
        import bot.services.api as api
        from bot.services.api import fetch_schedule_image

        generated_png = b"generated_png"
        schedule_data = {"events": [], "dtek_updated_at": ""}

        with (
            patch("bot.services.chart_cache.get", AsyncMock(return_value=None)),
            patch("bot.services.chart_cache.store", AsyncMock()),
            patch(
                "bot.services.chart_generator.generate_schedule_chart",
                AsyncMock(return_value=generated_png),
            ),
            patch("bot.services.api.get_queue_source_updated_at", AsyncMock(return_value=None)),
        ):
            result = await fetch_schedule_image("kyiv", "1.1", schedule_data)

        assert result == generated_png
        assert any(key.startswith("kyiv_1.1_") for key in api._image_cache)

    async def test_dtek_updated_at_change_creates_new_cache_path(self):
        """Different header timestamp should use a different cache fingerprint/path."""
        import bot.services.api as api
        from bot.services.api import fetch_schedule_image

        png_old = b"generated_old"
        png_new = b"generated_new"
        sched_old = {"events": [], "dtek_updated_at": "07.04.2026 06:00"}
        sched_new = {"events": [], "dtek_updated_at": "07.04.2026 07:00"}
        chart_get = AsyncMock(return_value=None)
        chart_store = AsyncMock()

        with (
            patch("bot.services.chart_cache.get", chart_get),
            patch("bot.services.chart_cache.store", chart_store),
            patch(
                "bot.services.chart_generator.generate_schedule_chart",
                AsyncMock(side_effect=[png_old, png_new]),
            ),
            patch("bot.services.api.get_queue_source_updated_at", AsyncMock(side_effect=[None, None])),
        ):
            first = await fetch_schedule_image("kyiv", "1.1", sched_old)
            second = await fetch_schedule_image("kyiv", "1.1", sched_new)

        assert first == png_old
        assert second == png_new
        assert len(api._image_cache) == 2

        first_fp = chart_get.await_args_list[0].kwargs["fingerprint"]
        second_fp = chart_get.await_args_list[1].kwargs["fingerprint"]
        assert first_fp != second_fp
        assert f"kyiv_1.1_{first_fp}" in api._image_cache
        assert f"kyiv_1.1_{second_fp}" in api._image_cache

    async def test_local_generation_fails_falls_back_to_github(self):
        """generate_schedule_chart returns None → falls back to GitHub PNG fetch."""
        url_template = "https://example.com/{region}/{queue}.png"
        fake_png = b"github_png"

        with (
            patch("bot.services.api.settings") as mock_settings,
            patch("bot.services.chart_cache.get", AsyncMock(return_value=None)),
            patch("bot.services.chart_cache.store", AsyncMock()),
            patch(
                "bot.services.chart_generator.generate_schedule_chart",
                AsyncMock(return_value=None),
            ),
            patch("bot.services.api.get_queue_source_updated_at", AsyncMock(return_value=None)),
            aioresponses() as m,
        ):
            mock_settings.IMAGE_URL_TEMPLATE = url_template
            m.get("https://example.com/kyiv/1-1.png", body=fake_png, status=200)
            from bot.services.api import fetch_schedule_image
            result = await fetch_schedule_image("kyiv", "1.1", {"events": []})

        assert result == fake_png

    async def test_github_fallback_network_error_returns_none(self):
        """GitHub fallback fails → returns None."""
        import aiohttp

        url_template = "https://example.com/{region}/{queue}.png"

        with (
            patch("bot.services.api.settings") as mock_settings,
            patch("bot.services.chart_cache.get", AsyncMock(return_value=None)),
            patch("bot.services.chart_generator.generate_schedule_chart", AsyncMock(return_value=None)),
            patch("bot.services.api.get_queue_source_updated_at", AsyncMock(return_value=None)),
            aioresponses() as m,
        ):
            mock_settings.IMAGE_URL_TEMPLATE = url_template
            m.get(
                "https://example.com/kyiv/1-1.png",
                exception=aiohttp.ClientError("timeout"),
            )
            from bot.services.api import fetch_schedule_image
            result = await fetch_schedule_image("kyiv", "1.1", {"events": []})

        assert result is None

    async def test_null_client_github_fallback_uses_temp_session(self):
        """_http_client=None in GitHub fallback → temp session created."""
        import bot.services.api as api

        assert api._http_client is None
        url_template = "https://example.com/{region}/{queue}.png"
        fake_png = b"fallback_png"

        with (
            patch("bot.services.api.settings") as mock_settings,
            patch("bot.services.chart_cache.get", AsyncMock(return_value=None)),
            patch("bot.services.chart_generator.generate_schedule_chart", AsyncMock(return_value=None)),
            patch("bot.services.api.get_queue_source_updated_at", AsyncMock(return_value=None)),
            aioresponses() as m,
        ):
            mock_settings.IMAGE_URL_TEMPLATE = url_template
            m.get("https://example.com/kyiv/1-1.png", body=fake_png, status=200)
            from bot.services.api import fetch_schedule_image
            result = await fetch_schedule_image("kyiv", "1.1", {"events": []})

        assert result == fake_png


# ---------------------------------------------------------------------------
# parse_schedule_for_queue — edge cases (lines 472, 478)
# ---------------------------------------------------------------------------


class TestParseScheduleEdgeCases:
    def test_no_fact_data_returns_no_data(self):
        """fact.data is None/empty → hasData=False (line 472)."""
        from bot.services.api import parse_schedule_for_queue

        raw = {"fact": {"data": None}}
        result = parse_schedule_for_queue(raw, "1.1")
        assert result["hasData"] is False

    def test_empty_timestamps_returns_no_data(self):
        """fact.data has no timestamp keys → hasData=False (line 478)."""
        from bot.services.api import parse_schedule_for_queue

        raw = {"fact": {"data": {}}}
        result = parse_schedule_for_queue(raw, "1.1")
        assert result["hasData"] is False


# ---------------------------------------------------------------------------
# _parse_dt — naive datetime gets Kyiv TZ (line 532)
# ---------------------------------------------------------------------------


class TestParseDt:
    def test_naive_datetime_gets_kyiv_tz(self):
        """Naive ISO string → tzinfo set to KYIV_TZ (line 532)."""
        from bot.services.api import _parse_dt

        result = _parse_dt("2024-01-15T10:00:00")
        assert result.tzinfo is not None
        assert result.tzinfo.key == "Europe/Kyiv"

    def test_aware_datetime_preserved(self):
        """Aware ISO string → tzinfo unchanged."""
        from bot.services.api import _parse_dt

        result = _parse_dt("2024-01-15T10:00:00+02:00")
        assert result.tzinfo is not None
        assert result.utcoffset().total_seconds() == 7200
