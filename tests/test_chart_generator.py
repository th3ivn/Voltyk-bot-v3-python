"""Tests for bot/services/chart_generator.py, and coverage gaps in
bot/services/chart_cache.py and bot/services/branding.py."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

KYIV_TZ = ZoneInfo("Europe/Kyiv")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_telegram_api_error():
    from aiogram.exceptions import TelegramAPIError
    method = MagicMock()
    return TelegramAPIError(method=method, message="Some API error")


def _make_schedule_data(*, today_events=None, tomorrow_events=None, dtek_updated_at=None):
    """Build a minimal schedule_data dict for chart tests."""
    events = []
    if today_events is not None:
        events.extend(today_events)
    if tomorrow_events is not None:
        events.extend(tomorrow_events)

    result = {"events": events}
    if dtek_updated_at is not None:
        result["dtek_updated_at"] = dtek_updated_at
    return result


def _off_event(day_start: datetime, start_h: int, end_h: int, possible: bool = False) -> dict:
    return {
        "start": (day_start + timedelta(hours=start_h)).isoformat(),
        "end": (day_start + timedelta(hours=end_h)).isoformat(),
        "isPossible": possible,
    }


# ===========================================================================
# bot/services/chart_generator.py — pure helper functions
# ===========================================================================

class TestEsc:
    def test_ampersand(self):
        from bot.services.chart_generator import _esc
        assert _esc("a & b") == "a &amp; b"

    def test_lt_gt(self):
        from bot.services.chart_generator import _esc
        assert _esc("<tag>") == "&lt;tag&gt;"

    def test_quote(self):
        from bot.services.chart_generator import _esc
        assert _esc('"hello"') == "&quot;hello&quot;"

    def test_no_special_chars(self):
        from bot.services.chart_generator import _esc
        assert _esc("plain text") == "plain text"


class TestParseDt:
    def test_from_iso_string(self):
        from bot.services.chart_generator import _parse_dt
        dt = _parse_dt("2024-03-15T10:30:00+00:00")
        assert dt.tzinfo is not None

    def test_from_datetime_object(self):
        import datetime as dt_mod

        from bot.services.chart_generator import _parse_dt
        obj = dt_mod.datetime(2024, 3, 15, 10, 30, tzinfo=ZoneInfo("UTC"))
        result = _parse_dt(obj)
        assert result.tzinfo is not None


class TestDayLabel:
    def test_first_january(self):
        from bot.services.chart_generator import _day_label
        dt = datetime(2024, 1, 1, tzinfo=KYIV_TZ)
        assert _day_label(dt) == "1 січня"

    def test_december(self):
        from bot.services.chart_generator import _day_label
        dt = datetime(2024, 12, 25, tzinfo=KYIV_TZ)
        assert _day_label(dt) == "25 грудня"

    def test_all_months(self):
        from bot.services.chart_generator import MONTHS_UK, _day_label
        for month_idx in range(1, 13):
            dt = datetime(2024, month_idx, 5, tzinfo=KYIV_TZ)
            label = _day_label(dt)
            assert MONTHS_UK[month_idx - 1] in label


class TestGetHourStates:
    """Tests for _get_hour_states — pure mapping logic."""

    def _day_start(self) -> datetime:
        return datetime(2024, 6, 1, tzinfo=KYIV_TZ)

    def test_no_events_all_on(self):
        from bot.services.chart_generator import _get_hour_states
        states = _get_hour_states([], self._day_start())
        assert len(states) == 24
        assert all(s == "on" for s in states)

    def test_full_day_off(self):
        from bot.services.chart_generator import _get_hour_states
        day = self._day_start()
        events = [_off_event(day, 0, 24, possible=False)]
        states = _get_hour_states(events, day)
        assert len(states) == 24
        assert all(s == "no" for s in states)

    def test_full_day_maybe(self):
        from bot.services.chart_generator import _get_hour_states
        day = self._day_start()
        events = [_off_event(day, 0, 24, possible=True)]
        states = _get_hour_states(events, day)
        assert len(states) == 24
        assert all(s == "maybe" for s in states)

    def test_partial_off_first_half(self):
        """Event covers first 30 min of an hour → nfirst (no+on)."""
        from bot.services.chart_generator import _get_hour_states
        day = self._day_start()
        # 08:00–08:30 off
        events = [{
            "start": (day + timedelta(hours=8)).isoformat(),
            "end": (day + timedelta(hours=8, minutes=30)).isoformat(),
            "isPossible": False,
        }]
        states = _get_hour_states(events, day)
        assert states[8] == "nfirst"

    def test_partial_off_second_half(self):
        """Event covers second 30 min of an hour → nsecond (on+no)."""
        from bot.services.chart_generator import _get_hour_states
        day = self._day_start()
        events = [{
            "start": (day + timedelta(hours=8, minutes=30)).isoformat(),
            "end": (day + timedelta(hours=9)).isoformat(),
            "isPossible": False,
        }]
        states = _get_hour_states(events, day)
        assert states[8] == "nsecond"

    def test_partial_maybe_first_half(self):
        from bot.services.chart_generator import _get_hour_states
        day = self._day_start()
        events = [{
            "start": (day + timedelta(hours=10)).isoformat(),
            "end": (day + timedelta(hours=10, minutes=30)).isoformat(),
            "isPossible": True,
        }]
        states = _get_hour_states(events, day)
        assert states[10] == "mfirst"

    def test_partial_maybe_second_half(self):
        from bot.services.chart_generator import _get_hour_states
        day = self._day_start()
        events = [{
            "start": (day + timedelta(hours=10, minutes=30)).isoformat(),
            "end": (day + timedelta(hours=11)).isoformat(),
            "isPossible": True,
        }]
        states = _get_hour_states(events, day)
        assert states[10] == "msecond"

    def test_mixed_both_halves_no_and_maybe(self):
        """When both halves are set but with different types → fallback."""
        from bot.services.chart_generator import _get_hour_states
        day = self._day_start()
        # First half: definite off; second half: possible off
        events = [
            {
                "start": (day + timedelta(hours=5)).isoformat(),
                "end": (day + timedelta(hours=5, minutes=30)).isoformat(),
                "isPossible": False,
            },
            {
                "start": (day + timedelta(hours=5, minutes=30)).isoformat(),
                "end": (day + timedelta(hours=6)).isoformat(),
                "isPossible": True,
            },
        ]
        states = _get_hour_states(events, day)
        # Falls into the else branch: 1 in (f, s) → "no"
        assert states[5] == "no"


class TestIconSvg:
    def test_returns_svg_string(self):
        from bot.services.chart_generator import _icon_svg
        result = _icon_svg(0.0, 0.0, 37.0, 46.0, [("M0 0Z", "#000000")])
        assert "<svg" in result
        assert "viewBox" in result

    def test_multiple_paths(self):
        from bot.services.chart_generator import _icon_svg
        paths = [("M0 0Z", "#ff0000"), ("M10 10Z", "#00ff00")]
        result = _icon_svg(5.0, 5.0, 37.0, 46.0, paths)
        assert result.count("<path") == 2


class TestHalfIconSvg:
    def test_both_halves(self):
        from bot.services.chart_generator import _half_icon_svg
        result = _half_icon_svg(
            0.0, 0.0, 37.0, 46.0,
            [("M0 0Z", "#000000")],
            [("M10 0Z", "#ffffff")],
        )
        assert result.count("<svg") == 2

    def test_left_only(self):
        from bot.services.chart_generator import _half_icon_svg
        result = _half_icon_svg(
            0.0, 0.0, 37.0, 46.0,
            [("M0 0Z", "#000000")],
            [],
        )
        assert result.count("<svg") == 1

    def test_right_only(self):
        from bot.services.chart_generator import _half_icon_svg
        result = _half_icon_svg(
            0.0, 0.0, 37.0, 46.0,
            [],
            [("M10 0Z", "#ffffff")],
        )
        assert result.count("<svg") == 1

    def test_both_empty(self):
        from bot.services.chart_generator import _half_icon_svg
        result = _half_icon_svg(0.0, 0.0, 37.0, 46.0, [], [])
        assert result == ""


class TestCellSvg:
    """Tests for _cell_svg — one cell SVG for each state."""

    def _call(self, state: str) -> str:
        from bot.services.chart_generator import _cell_svg
        return _cell_svg(100.0, 50.0, state)

    def test_on_state(self):
        svg = self._call("on")
        assert "<rect" in svg

    def test_no_state(self):
        svg = self._call("no")
        assert "<rect" in svg
        assert "<svg" in svg  # icon embedded

    def test_maybe_state(self):
        svg = self._call("maybe")
        assert "<rect" in svg
        assert "<svg" in svg

    def test_nfirst_state(self):
        svg = self._call("nfirst")
        assert svg.count("<rect") == 2

    def test_nsecond_state(self):
        svg = self._call("nsecond")
        assert svg.count("<rect") == 2

    def test_mfirst_state(self):
        svg = self._call("mfirst")
        assert svg.count("<rect") == 2

    def test_msecond_state(self):
        svg = self._call("msecond")
        assert svg.count("<rect") == 2

    def test_unknown_state_fallback(self):
        svg = self._call("unknown_state")
        assert "<rect" in svg


class TestLegendSwatch:
    def _call(self, state: str) -> str:
        from bot.services.chart_generator import _legend_swatch
        return _legend_swatch(10.0, 20.0, state, 37.0, 46.0)

    def test_on(self):
        assert "<rect" in self._call("on")

    def test_no(self):
        svg = self._call("no")
        assert "<rect" in svg
        assert "<svg" in svg

    def test_maybe(self):
        svg = self._call("maybe")
        assert "<rect" in svg

    def test_nfirst(self):
        svg = self._call("nfirst")
        assert svg.count("<rect") >= 2

    def test_nsecond(self):
        svg = self._call("nsecond")
        assert svg.count("<rect") >= 2


class TestBuildSvg:
    """Tests for _build_svg — generates a complete SVG document."""

    def _build(self, region="kyiv", queue="1.1", schedule_data=None):
        from bot.services.chart_generator import _build_svg
        if schedule_data is None:
            schedule_data = _make_schedule_data()
        return _build_svg(region, queue, schedule_data)

    def test_returns_valid_svg(self):
        svg = self._build()
        assert svg.startswith("<svg")
        assert svg.endswith("</svg>")

    def test_contains_region_label(self):
        svg = self._build(region="kyiv")
        assert "Київ" in svg

    def test_unknown_region_uses_code(self):
        svg = self._build(region="unknown_region")
        assert "unknown_region" in svg

    def test_queue_in_badge(self):
        svg = self._build(queue="3.2")
        assert "Черга: 3.2" in svg

    def test_with_dtek_updated_at_valid(self):
        data = _make_schedule_data(dtek_updated_at="15.03.2024 10:30")
        svg = self._build(schedule_data=data)
        assert "Останнє оновлення графіка станом на 10:30 15.03.2024" in svg

    def test_with_dtek_updated_at_invalid_format(self):
        data = _make_schedule_data(dtek_updated_at="not-a-date")
        svg = self._build(schedule_data=data)
        assert "Останнє оновлення графіка станом на" in svg

    def test_normalizer_fills_timestamp_before_render(self):
        from bot.services.api import normalize_schedule_chart_metadata

        normalized, _ = normalize_schedule_chart_metadata(_make_schedule_data(), 1710501000)
        svg = self._build(schedule_data=normalized)

        assert normalized["dtek_updated_at"] == "15.03.2024 13:10"
        assert "Останнє оновлення графіка станом на 13:10 15.03.2024" in svg

    def test_all_cells_on(self):
        svg = self._build(schedule_data=_make_schedule_data())
        # No off events → all on, no slash icon paths
        assert "<svg" in svg

    def test_all_cells_off(self):
        now = datetime.now(KYIV_TZ)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        events = [
            _off_event(today_start, 0, 24, possible=False),
            _off_event(tomorrow_start, 0, 24, possible=False),
        ]
        data = {"events": events}
        svg = self._build(schedule_data=data)
        assert svg.endswith("</svg>")

    def test_mixed_events(self):
        now = datetime.now(KYIV_TZ)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        events = [_off_event(today_start, 8, 12)]
        data = {"events": events}
        svg = self._build(schedule_data=data)
        assert svg.endswith("</svg>")

    def test_badge_overflow_scaling(self):
        """Very long region/queue names trigger badge width scaling."""
        data = _make_schedule_data(dtek_updated_at="01.01.2024 00:00")
        svg = self._build(
            region="kyiv",
            queue="1.1",
            schedule_data=data,
        )
        assert "url(#bdg)" in svg

    def test_badge_width_scaling_applied_when_combined_too_wide(self):
        """Lines 402-404: left_bw + right_bw > TABLE_W-16 triggers proportional scaling."""
        # Use a dtek_updated_at that doesn't match strptime → raw 60-char left_txt
        data = _make_schedule_data(dtek_updated_at="A" * 60)
        svg = self._build(
            region="kyiv",
            queue="X" * 60,
            schedule_data=data,
        )
        assert svg.endswith("</svg>")

    def test_different_regions(self):
        for region in ("kyiv", "kyiv-region", "dnipro", "odesa"):
            svg = self._build(region=region)
            assert svg.endswith("</svg>")


# ===========================================================================
# _generate_sync
# ===========================================================================

class TestGenerateSync:
    def test_returns_none_when_cairosvg_missing(self):
        from bot.services.chart_generator import _generate_sync
        # Simulate ImportError for cairosvg
        with patch.dict(sys.modules, {"cairosvg": None}):
            result = _generate_sync("kyiv", "1.1", _make_schedule_data())
        assert result is None

    def test_returns_bytes_when_cairosvg_available(self):
        from bot.services.chart_generator import _generate_sync
        mock_cairosvg = MagicMock()
        mock_cairosvg.svg2png.return_value = b"PNG_DATA"
        with patch.dict(sys.modules, {"cairosvg": mock_cairosvg}):
            result = _generate_sync("kyiv", "1.1", _make_schedule_data())
        assert result == b"PNG_DATA"

    def test_returns_none_on_render_error(self):
        from bot.services.chart_generator import _generate_sync
        mock_cairosvg = MagicMock()
        mock_cairosvg.svg2png.side_effect = RuntimeError("render failed")
        with patch.dict(sys.modules, {"cairosvg": mock_cairosvg}):
            result = _generate_sync("kyiv", "1.1", _make_schedule_data())
        assert result is None


# ===========================================================================
# generate_schedule_chart (async wrapper)
# ===========================================================================

class TestGenerateScheduleChart:
    async def test_success(self):
        from bot.services.chart_generator import generate_schedule_chart
        with patch("bot.services.chart_generator._generate_sync", return_value=b"PNG"):
            result = await generate_schedule_chart("kyiv", "1.1", _make_schedule_data())
        assert result == b"PNG"

    async def test_timeout_returns_none(self):
        import asyncio

        from bot.services.chart_generator import generate_schedule_chart

        async def _slow(*_args, **_kwargs):
            raise asyncio.TimeoutError()

        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            result = await generate_schedule_chart("kyiv", "1.1", _make_schedule_data())
        assert result is None

    async def test_exception_returns_none(self):
        from bot.services.chart_generator import generate_schedule_chart
        with patch("bot.services.chart_generator._generate_sync", side_effect=RuntimeError("boom")):
            result = await generate_schedule_chart("kyiv", "1.1", _make_schedule_data())
        assert result is None


# ===========================================================================
# shutdown_chart_executor
# ===========================================================================

class TestShutdownChartExecutor:
    def test_shutdown_called(self):
        from bot.services.chart_generator import _chart_executor, shutdown_chart_executor
        with patch.object(_chart_executor, "shutdown") as mock_shutdown:
            shutdown_chart_executor()
        mock_shutdown.assert_called_once_with(wait=False)


# ===========================================================================
# bot/services/chart_cache.py — coverage gaps
# ===========================================================================

class TestChartCacheInitNoUrl:
    """Lines 41-43: init() when REDIS_URL is empty."""

    async def test_init_with_empty_redis_url(self):
        from bot.services import chart_cache

        original = chart_cache._redis
        try:
            with patch("bot.services.chart_cache.settings") as mock_settings:
                mock_settings.REDIS_URL = ""
                await chart_cache.init()
            assert chart_cache._redis is None
        finally:
            chart_cache._redis = original


class TestChartCachePing:
    """Lines 85-88: ping() function."""

    def setup_method(self):
        from bot.services import chart_cache
        self._original = chart_cache._redis
        chart_cache._redis = None

    def teardown_method(self):
        from bot.services import chart_cache
        chart_cache._redis = self._original

    async def test_ping_returns_false_when_no_redis(self):
        from bot.services import chart_cache
        result = await chart_cache.ping()
        assert result is False

    async def test_ping_returns_true_on_success(self):
        from bot.services import chart_cache
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        chart_cache._redis = mock_redis
        result = await chart_cache.ping()
        assert result is True
        mock_redis.ping.assert_called_once()

    async def test_ping_raises_on_failure(self):
        from bot.services import chart_cache
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("refused"))
        chart_cache._redis = mock_redis
        with pytest.raises(ConnectionError):
            await chart_cache.ping()


# ===========================================================================
# bot/services/branding.py — coverage gaps (lines 50, 60, 68, 83)
# ===========================================================================

class TestApplyChannelBrandingTelegramAPIErrors:
    """Cover TelegramAPIError catch blocks in apply_channel_branding."""

    def _make_cc(self, **kwargs):
        defaults = dict(
            channel_id=-1001234567890,
            channel_user_title="Test Channel",
            channel_user_description="Test Desc",
            channel_title=None,
            channel_description=None,
            channel_branding_updated_at=None,
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def _make_bot(self, **overrides):
        bot = AsyncMock()
        bot.get_me = AsyncMock(return_value=SimpleNamespace(username="voltyk_bot"))
        bot.set_chat_title = AsyncMock()
        bot.set_chat_description = AsyncMock()
        bot.set_chat_photo = AsyncMock()
        bot.send_message = AsyncMock()
        for key, val in overrides.items():
            setattr(bot, key, val)
        return bot

    async def test_set_chat_title_telegram_api_error(self):
        """Line 50: TelegramAPIError when setting title."""
        from bot.services.branding import apply_channel_branding
        error = _make_telegram_api_error()
        bot = self._make_bot(set_chat_title=AsyncMock(side_effect=error))
        cc = self._make_cc()
        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_photo:
            mock_photo.exists.return_value = False
            await apply_channel_branding(bot, cc)
        # Should not raise, title not updated
        assert cc.channel_title is None

    async def test_set_chat_description_telegram_api_error(self):
        """Line 60: TelegramAPIError when setting description."""
        from bot.services.branding import apply_channel_branding
        error = _make_telegram_api_error()
        bot = self._make_bot(set_chat_description=AsyncMock(side_effect=error))
        cc = self._make_cc()
        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_photo, \
             patch("bot.services.branding.build_channel_description", return_value="A description"):
            mock_photo.exists.return_value = False
            await apply_channel_branding(bot, cc)
        assert cc.channel_description is None

    async def test_set_chat_photo_telegram_api_error(self):
        """Line 68: TelegramAPIError when setting photo."""
        from bot.services.branding import apply_channel_branding
        error = _make_telegram_api_error()
        bot = self._make_bot(set_chat_photo=AsyncMock(side_effect=error))
        cc = self._make_cc()
        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_photo, \
             patch("bot.services.branding.FSInputFile"):
            mock_photo.exists.return_value = True
            await apply_channel_branding(bot, cc)
        assert cc.channel_branding_updated_at is not None

    async def test_send_welcome_message_telegram_api_error(self):
        """Line 83: TelegramAPIError when sending welcome message."""
        from bot.services.branding import apply_channel_branding
        error = _make_telegram_api_error()
        bot = self._make_bot(send_message=AsyncMock(side_effect=error))
        cc = self._make_cc()
        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_photo:
            mock_photo.exists.return_value = False
            await apply_channel_branding(
                bot, cc, send_welcome=True, queue="1.1", region="kyiv"
            )
        assert cc.channel_branding_updated_at is not None

    async def test_set_chat_title_generic_exception(self):
        """Line 52 path: unexpected Exception when setting title."""
        from bot.services.branding import apply_channel_branding
        bot = self._make_bot(set_chat_title=AsyncMock(side_effect=ValueError("oops")))
        cc = self._make_cc()
        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_photo:
            mock_photo.exists.return_value = False
            await apply_channel_branding(bot, cc)
        assert cc.channel_branding_updated_at is not None

    async def test_set_chat_description_generic_exception(self):
        """Line 62 path: unexpected Exception when setting description."""
        from bot.services.branding import apply_channel_branding
        bot = self._make_bot(set_chat_description=AsyncMock(side_effect=ValueError("bad")))
        cc = self._make_cc()
        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_photo, \
             patch("bot.services.branding.build_channel_description", return_value="Desc"):
            mock_photo.exists.return_value = False
            await apply_channel_branding(bot, cc)
        assert cc.channel_branding_updated_at is not None

    async def test_send_welcome_message_generic_exception(self):
        """Line 85 path: unexpected Exception when sending welcome."""
        from bot.services.branding import apply_channel_branding
        bot = self._make_bot(send_message=AsyncMock(side_effect=RuntimeError("net")))
        cc = self._make_cc()
        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_photo:
            mock_photo.exists.return_value = False
            await apply_channel_branding(
                bot, cc, send_welcome=True, queue="1.1"
            )
        assert cc.channel_branding_updated_at is not None
