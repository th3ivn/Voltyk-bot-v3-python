"""Tests for bot/services/api.py — pure parsing functions."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

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
        assert len(result) == 32  # md5 hex digest length

    def test_order_matters(self):
        e1 = {"start": "2024-01-01T10:00:00", "end": "2024-01-01T12:00:00"}
        e2 = {"start": "2024-01-01T14:00:00", "end": "2024-01-01T16:00:00"}
        hash1 = calculate_schedule_hash([e1, e2])
        hash2 = calculate_schedule_hash([e2, e1])
        assert hash1 != hash2
