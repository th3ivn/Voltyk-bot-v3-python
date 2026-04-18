"""Tests for bot/services/api.py — pure parsing functions."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from bot.services.api import (
    _add_or_extend,
    _hour_to_datetime,
    _merge_consecutive,
    _parse_hourly_schedule,
    calculate_schedule_hash,
    find_next_event,
    parse_schedule_for_queue,
)

KYIV_TZ = ZoneInfo("Europe/Kyiv")


def _kyiv_now() -> datetime:
    return datetime.now(KYIV_TZ)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ─── _hour_to_datetime ────────────────────────────────────────────────────


class TestHourToDatetime:
    def _base(self, hour_offset: int = 0) -> datetime:
        return (_kyiv_now() + timedelta(days=hour_offset)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    def test_whole_hour(self):
        base = self._base()
        result = _hour_to_datetime(base, 13)
        assert result.hour == 13
        assert result.minute == 0

    def test_half_hour(self):
        base = self._base()
        result = _hour_to_datetime(base, 13.5)
        assert result.hour == 13
        assert result.minute == 30

    def test_hour_24_rolls_over_to_midnight_next_day(self):
        base = self._base()
        result = _hour_to_datetime(base, 24)
        # 00:00 next day
        assert result.hour == 0
        assert result.minute == 0
        assert result.date() == (base + timedelta(days=1)).date()

    def test_hour_zero(self):
        base = self._base()
        result = _hour_to_datetime(base, 0)
        assert result.hour == 0
        assert result.minute == 0

    def test_hour_1(self):
        base = self._base()
        result = _hour_to_datetime(base, 1)
        assert result.hour == 1


# ─── _add_or_extend ───────────────────────────────────────────────────────


class TestAddOrExtend:
    def test_empty_list_creates_new_period(self):
        periods: list[dict] = []
        _add_or_extend(periods, 0, 1)
        assert periods == [{"start": 0, "end": 1}]

    def test_consecutive_extends_last_period(self):
        periods = [{"start": 0, "end": 1}]
        _add_or_extend(periods, 1, 2)
        assert periods == [{"start": 0, "end": 2}]

    def test_non_consecutive_creates_new_period(self):
        periods = [{"start": 0, "end": 1}]
        _add_or_extend(periods, 2, 3)
        assert periods == [{"start": 0, "end": 1}, {"start": 2, "end": 3}]


# ─── _merge_consecutive ───────────────────────────────────────────────────


class TestMergeConsecutive:
    def test_empty_list(self):
        assert _merge_consecutive([]) == []

    def test_single_period_unchanged(self):
        periods = [{"start": 1, "end": 2}]
        result = _merge_consecutive(periods)
        assert result == [{"start": 1, "end": 2}]

    def test_merges_adjacent_periods(self):
        periods = [{"start": 1, "end": 2}, {"start": 2, "end": 3}]
        result = _merge_consecutive(periods)
        assert result == [{"start": 1, "end": 3}]

    def test_does_not_merge_non_adjacent(self):
        periods = [{"start": 1, "end": 2}, {"start": 3, "end": 4}]
        result = _merge_consecutive(periods)
        assert result == [{"start": 1, "end": 2}, {"start": 3, "end": 4}]

    def test_merges_multiple_consecutive(self):
        periods = [
            {"start": 1, "end": 2},
            {"start": 2, "end": 3},
            {"start": 3, "end": 4},
        ]
        result = _merge_consecutive(periods)
        assert result == [{"start": 1, "end": 4}]

    def test_does_not_mutate_original(self):
        periods = [{"start": 1, "end": 2}, {"start": 2, "end": 3}]
        original_len = len(periods)
        _merge_consecutive(periods)
        assert len(periods) == original_len


# ─── _parse_hourly_schedule ───────────────────────────────────────────────


class TestParseHourlySchedule:
    def test_empty_dict_returns_empty_lists(self):
        planned, possible = _parse_hourly_schedule({})
        assert planned == []
        assert possible == []

    def test_no_outage_returns_empty(self):
        data = {str(h): "on" for h in range(1, 25)}
        planned, possible = _parse_hourly_schedule(data)
        assert planned == []
        assert possible == []

    def test_full_hour_outage_no(self):
        planned, possible = _parse_hourly_schedule({"14": "no"})
        assert len(planned) == 1
        assert possible == []
        # hour=14 "no" means 13:00-14:00
        p = planned[0]
        assert p["start"] == 13
        assert p["end"] == 14

    def test_possible_outage_maybe(self):
        planned, possible = _parse_hourly_schedule({"10": "maybe"})
        assert planned == []
        assert len(possible) == 1
        p = possible[0]
        assert p["start"] == 9
        assert p["end"] == 10

    def test_first_half_outage(self):
        planned, possible = _parse_hourly_schedule({"14": "first"})
        assert len(planned) == 1
        # first half: 13:00-13:30
        p = planned[0]
        assert p["start"] == 13
        assert p["end"] == 13.5

    def test_second_half_outage(self):
        planned, possible = _parse_hourly_schedule({"14": "second"})
        assert len(planned) == 1
        # second half: 13:30-14:00
        p = planned[0]
        assert p["start"] == 13.5
        assert p["end"] == 14

    def test_consecutive_hours_merged(self):
        data = {"10": "no", "11": "no"}
        planned, _ = _parse_hourly_schedule(data)
        assert len(planned) == 1
        assert planned[0]["start"] == 9
        assert planned[0]["end"] == 11

    def test_integer_keys_also_work(self):
        data = {14: "no"}
        planned, _ = _parse_hourly_schedule(data)
        assert len(planned) == 1


# ─── parse_schedule_for_queue ─────────────────────────────────────────────


class TestParseScheduleForQueue:
    def _make_raw(self, queue: str = "1", hours: dict | None = None) -> dict:
        """Build a minimal raw API response."""
        if hours is None:
            hours = {"14": "no"}
        now = _kyiv_now()
        today_ts = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        return {
            "fact": {
                "data": {
                    str(today_ts): {
                        f"GPV{queue}": hours,
                    }
                }
            }
        }

    def test_none_input_returns_no_data(self):
        result = parse_schedule_for_queue(None, "1.1")
        assert result["hasData"] is False
        assert result["events"] == []

    def test_empty_dict_returns_no_data(self):
        result = parse_schedule_for_queue({}, "1.1")
        assert result["hasData"] is False

    def test_missing_fact_key_returns_no_data(self):
        result = parse_schedule_for_queue({"other": {}}, "1.1")
        assert result["hasData"] is False

    def test_valid_data_returns_events(self):
        raw = self._make_raw(queue="1.1", hours={"14": "no"})
        result = parse_schedule_for_queue(raw, "1.1")
        assert result["hasData"] is True
        assert len(result["events"]) > 0

    def test_events_have_required_keys(self):
        raw = self._make_raw(queue="1.1", hours={"14": "no"})
        result = parse_schedule_for_queue(raw, "1.1")
        for ev in result["events"]:
            assert "start" in ev
            assert "end" in ev
            assert "isPossible" in ev

    def test_events_are_sorted_by_start(self):
        raw = self._make_raw(queue="1.1", hours={"10": "no", "15": "no"})
        result = parse_schedule_for_queue(raw, "1.1")
        starts = [ev["start"] for ev in result["events"]]
        assert starts == sorted(starts)

    def test_queue_returned_in_result(self):
        raw = self._make_raw(queue="1.1")
        result = parse_schedule_for_queue(raw, "1.1")
        assert result["queue"] == "1.1"

    def test_possible_event_flagged(self):
        raw = self._make_raw(queue="1.1", hours={"14": "maybe"})
        result = parse_schedule_for_queue(raw, "1.1")
        assert result["hasData"] is True
        assert any(ev["isPossible"] for ev in result["events"])

    def test_no_outages_returns_no_data(self):
        raw = self._make_raw(queue="1.1", hours={})
        result = parse_schedule_for_queue(raw, "1.1")
        assert result["hasData"] is False


# ─── find_next_event ──────────────────────────────────────────────────────


class TestFindNextEvent:
    def test_no_data_returns_none(self):
        result = find_next_event({"hasData": False, "events": []})
        assert result is None

    def test_empty_events_returns_none(self):
        result = find_next_event({"hasData": True, "events": []})
        assert result is None

    def test_future_event_returns_power_off(self):
        now = _kyiv_now()
        start = (now + timedelta(hours=1)).replace(second=0, microsecond=0)
        end = (now + timedelta(hours=2)).replace(second=0, microsecond=0)
        events = [{"start": _iso(start), "end": _iso(end), "isPossible": False}]
        result = find_next_event({"hasData": True, "events": events})
        assert result is not None
        assert result["type"] == "power_off"
        assert result["minutes"] > 0

    def test_current_outage_returns_power_on(self):
        now = _kyiv_now()
        start = (now - timedelta(hours=1)).replace(second=0, microsecond=0)
        end = (now + timedelta(hours=1)).replace(second=0, microsecond=0)
        events = [{"start": _iso(start), "end": _iso(end), "isPossible": False}]
        result = find_next_event({"hasData": True, "events": events})
        assert result is not None
        assert result["type"] == "power_on"
        assert result["minutes"] > 0

    def test_all_past_events_returns_none(self):
        now = _kyiv_now()
        start = (now - timedelta(hours=3)).replace(second=0, microsecond=0)
        end = (now - timedelta(hours=2)).replace(second=0, microsecond=0)
        events = [{"start": _iso(start), "end": _iso(end), "isPossible": False}]
        result = find_next_event({"hasData": True, "events": events})
        assert result is None

    def test_consecutive_outages_merged_for_power_on(self):
        now = _kyiv_now()
        start1 = (now - timedelta(hours=1)).replace(second=0, microsecond=0)
        end1 = (now + timedelta(hours=1)).replace(second=0, microsecond=0)
        start2 = end1
        end2 = (now + timedelta(hours=2)).replace(second=0, microsecond=0)
        events = [
            {"start": _iso(start1), "end": _iso(end1), "isPossible": False},
            {"start": _iso(start2), "end": _iso(end2), "isPossible": False},
        ]
        result = find_next_event({"hasData": True, "events": events})
        assert result is not None
        assert result["type"] == "power_on"
        # Should point to end2, not end1
        assert result["time"] == _iso(end2)

    def test_possible_event_flagged(self):
        now = _kyiv_now()
        start = (now + timedelta(hours=1)).replace(second=0, microsecond=0)
        end = (now + timedelta(hours=2)).replace(second=0, microsecond=0)
        events = [{"start": _iso(start), "end": _iso(end), "isPossible": True}]
        result = find_next_event({"hasData": True, "events": events})
        assert result is not None
        assert result["isPossible"] is True

    def test_power_off_includes_end_time(self):
        now = _kyiv_now()
        start = (now + timedelta(hours=1)).replace(second=0, microsecond=0)
        end = (now + timedelta(hours=2)).replace(second=0, microsecond=0)
        events = [{"start": _iso(start), "end": _iso(end), "isPossible": False}]
        result = find_next_event({"hasData": True, "events": events})
        assert result["endTime"] == _iso(end)

    def test_power_on_includes_start_time(self):
        now = _kyiv_now()
        start = (now - timedelta(hours=1)).replace(second=0, microsecond=0)
        end = (now + timedelta(hours=1)).replace(second=0, microsecond=0)
        events = [{"start": _iso(start), "end": _iso(end), "isPossible": False}]
        result = find_next_event({"hasData": True, "events": events})
        assert result["startTime"] == _iso(start)


# ─── calculate_schedule_hash ─────────────────────────────────────────────


class TestCalculateScheduleHash:
    def test_same_input_same_hash(self):
        events = [{"start": "2024-01-01T10:00:00", "end": "2024-01-01T12:00:00"}]
        assert calculate_schedule_hash(events) == calculate_schedule_hash(events)

    def test_different_input_different_hash(self):
        events1 = [{"start": "2024-01-01T10:00:00", "end": "2024-01-01T12:00:00"}]
        events2 = [{"start": "2024-01-01T14:00:00", "end": "2024-01-01T16:00:00"}]
        assert calculate_schedule_hash(events1) != calculate_schedule_hash(events2)

    def test_empty_list(self):
        result = calculate_schedule_hash([])
        assert isinstance(result, str)
        assert len(result) == 64  # sha256 hex digest length

    def test_order_matters(self):
        e1 = {"start": "2024-01-01T10:00:00", "end": "2024-01-01T12:00:00"}
        e2 = {"start": "2024-01-01T14:00:00", "end": "2024-01-01T16:00:00"}
        hash1 = calculate_schedule_hash([e1, e2])
        hash2 = calculate_schedule_hash([e2, e1])
        assert hash1 != hash2


# ─── parse_schedule_for_queue: empty timestamps (line 478) ───────────────


class TestParseScheduleEmptyTimestamps:
    def test_truthy_fact_data_with_no_keys_returns_no_data(self):
        """Line 478: fact.data is truthy but has no keys → timestamps=[] → hasData=False."""

        class _TruthyEmptyDict(dict):
            def __bool__(self):
                return True

            def keys(self):
                return iter([])

        raw = {"fact": {"data": _TruthyEmptyDict()}}
        result = parse_schedule_for_queue(raw, "1.1")
        assert result["hasData"] is False
        assert result["events"] == []
        assert result["queue"] == "1.1"


# ─── fetch_schedule_data: CircuitBreakerOpen (lines 293-297) ─────────────


class TestFetchScheduleCircuitBreaker:
    async def test_circuit_open_returns_stale_cache(self):
        """Lines 293-296: CircuitBreakerOpen → return stale entry from cache."""
        import bot.services.api as api_mod
        from bot.utils.circuit_breaker import CircuitBreakerOpen

        stale = {"stale": True}
        async with api_mod._schedule_cache_lock:
            api_mod._schedule_cache["cb_test_region"] = (
                datetime.now() - timedelta(hours=1),
                stale,
            )
        try:
            with patch.object(
                api_mod._schedule_api_breaker,
                "call",
                side_effect=CircuitBreakerOpen("schedule_api", 60.0),
            ):
                result = await api_mod.fetch_schedule_data("cb_test_region", force_refresh=True)

            assert result == stale
        finally:
            async with api_mod._schedule_cache_lock:
                api_mod._schedule_cache.pop("cb_test_region", None)

    async def test_circuit_open_no_cache_returns_none(self):
        """Line 297: CircuitBreakerOpen with no cache entry → return None."""
        import bot.services.api as api_mod
        from bot.utils.circuit_breaker import CircuitBreakerOpen

        async with api_mod._schedule_cache_lock:
            api_mod._schedule_cache.pop("cb_empty_region", None)

        with patch.object(
            api_mod._schedule_api_breaker,
            "call",
            side_effect=CircuitBreakerOpen("schedule_api", 60.0),
        ):
            result = await api_mod.fetch_schedule_data("cb_empty_region", force_refresh=True)

        assert result is None


# ─── fetch_schedule_data: cache eviction (line 273) ──────────────────────


class TestFetchScheduleCacheEviction:
    async def test_oldest_entry_evicted_when_cache_full(self):
        """Line 273: when _schedule_cache has MAX_CACHE_SIZE entries, popitem evicts oldest."""
        import bot.services.api as api_mod
        from bot.services.api import MAX_CACHE_SIZE

        old_ts = datetime.now() - timedelta(hours=1)
        async with api_mod._schedule_cache_lock:
            api_mod._schedule_cache.clear()
            for i in range(MAX_CACHE_SIZE):
                api_mod._schedule_cache[f"evict_r_{i}"] = (old_ts, {"idx": i})

        assert len(api_mod._schedule_cache) == MAX_CACHE_SIZE
        first_key = next(iter(api_mod._schedule_cache))

        import json as _json
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.content = MagicMock()
        mock_resp.content.read = AsyncMock(return_value=_json.dumps({"data": "new"}).encode())
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_http = MagicMock()
        mock_http.get = MagicMock(return_value=mock_resp)

        try:
            with patch("bot.services.api._http_client", mock_http):
                result = await api_mod.fetch_schedule_data("evict_new_region", force_refresh=True)

            async with api_mod._schedule_cache_lock:
                assert len(api_mod._schedule_cache) == MAX_CACHE_SIZE
                assert first_key not in api_mod._schedule_cache
                assert "evict_new_region" in api_mod._schedule_cache

            assert result == {"data": "new"}
        finally:
            async with api_mod._schedule_cache_lock:
                for i in range(MAX_CACHE_SIZE):
                    api_mod._schedule_cache.pop(f"evict_r_{i}", None)
                api_mod._schedule_cache.pop("evict_new_region", None)


# ─── Response size limits ─────────────────────────────────────────────────


class TestResponseSizeLimits:
    """Tests for _MAX_COMMIT_RESPONSE, _MAX_JSON_RESPONSE, _MAX_IMAGE_RESPONSE guards."""

    async def test_github_commits_too_large_returns_true_none(self):
        """api.py:134-135: oversized GitHub commits response → (True, None)."""
        import bot.services.api as api_mod

        oversized = b"x" * (api_mod._MAX_COMMIT_RESPONSE + 2)
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {}
        mock_resp.content = MagicMock()
        mock_resp.content.read = AsyncMock(return_value=oversized)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_http = MagicMock()
        mock_http.get = MagicMock(return_value=mock_resp)

        with patch("bot.services.api._http_client", mock_http):
            result = await api_mod.check_source_repo_updated()

        assert result == (True, None)

    async def test_schedule_json_too_large_returns_none(self):
        """api.py:280-281: oversized schedule JSON response → None."""
        import bot.services.api as api_mod

        oversized = b"x" * (api_mod._MAX_JSON_RESPONSE + 2)
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.content = MagicMock()
        mock_resp.content.read = AsyncMock(return_value=oversized)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_http = MagicMock()
        mock_http.get = MagicMock(return_value=mock_resp)

        with patch("bot.services.api._http_client", mock_http):
            result = await api_mod.fetch_schedule_data("size_test_region", force_refresh=True)

        assert result is None

    async def test_image_too_large_returns_none(self):
        """api.py:410-411: oversized image response → None."""
        import bot.services.api as api_mod

        oversized = b"x" * (api_mod._MAX_IMAGE_RESPONSE + 2)
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.content = MagicMock()
        mock_resp.content.read = AsyncMock(return_value=oversized)
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_http = MagicMock()
        mock_http.get = MagicMock(return_value=mock_resp)

        with (
            patch("bot.services.api._http_client", mock_http),
            patch("bot.services.chart_cache.get", new_callable=AsyncMock, return_value=None),
        ):
            # Pass schedule_data=None to skip local generation and reach GitHub fallback
            result = await api_mod.fetch_schedule_image("size_img_region_unique_xz", "1.1", None)

        assert result is None
