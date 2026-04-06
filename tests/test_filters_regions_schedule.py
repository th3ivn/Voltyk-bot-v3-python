"""Unit tests for bot/filters/admin.py, bot/constants/regions.py, and bot/handlers/schedule.py."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import CallbackQuery, Message, TelegramObject


# ===========================================================================
# AdminFilter & OwnerFilter
# ===========================================================================


class TestAdminFilter:
    """Tests for bot/filters/admin.py — AdminFilter."""

    def _make_filter(self):
        from bot.filters.admin import AdminFilter

        return AdminFilter()

    async def test_message_from_admin_returns_true(self):
        flt = self._make_filter()
        event = MagicMock(spec=Message)
        event.from_user = SimpleNamespace(id=42)
        with patch("bot.filters.admin.settings") as mock_settings:
            mock_settings.is_admin.return_value = True
            result = await flt(event)
        assert result is True
        mock_settings.is_admin.assert_called_once_with(42)

    async def test_message_from_non_admin_returns_false(self):
        flt = self._make_filter()
        event = MagicMock(spec=Message)
        event.from_user = SimpleNamespace(id=99)
        with patch("bot.filters.admin.settings") as mock_settings:
            mock_settings.is_admin.return_value = False
            result = await flt(event)
        assert result is False

    async def test_callback_query_from_admin_returns_true(self):
        flt = self._make_filter()
        event = MagicMock(spec=CallbackQuery)
        event.from_user = SimpleNamespace(id=7)
        with patch("bot.filters.admin.settings") as mock_settings:
            mock_settings.is_admin.return_value = True
            result = await flt(event)
        assert result is True

    async def test_callback_query_from_non_admin_returns_false(self):
        flt = self._make_filter()
        event = MagicMock(spec=CallbackQuery)
        event.from_user = SimpleNamespace(id=999)
        with patch("bot.filters.admin.settings") as mock_settings:
            mock_settings.is_admin.return_value = False
            result = await flt(event)
        assert result is False

    async def test_message_without_from_user_returns_false(self):
        flt = self._make_filter()
        event = MagicMock(spec=Message)
        event.from_user = None
        with patch("bot.filters.admin.settings") as mock_settings:
            result = await flt(event)
        assert result is False
        mock_settings.is_admin.assert_not_called()

    async def test_non_message_telegram_object_returns_false(self):
        flt = self._make_filter()
        event = MagicMock(spec=TelegramObject)
        with patch("bot.filters.admin.settings") as mock_settings:
            result = await flt(event)
        assert result is False
        mock_settings.is_admin.assert_not_called()


class TestOwnerFilter:
    """Tests for bot/filters/admin.py — OwnerFilter."""

    def _make_filter(self):
        from bot.filters.admin import OwnerFilter

        return OwnerFilter()

    async def test_message_from_owner_returns_true(self):
        flt = self._make_filter()
        event = MagicMock(spec=Message)
        event.from_user = SimpleNamespace(id=1)
        with patch("bot.filters.admin.settings") as mock_settings:
            mock_settings.is_owner.return_value = True
            result = await flt(event)
        assert result is True
        mock_settings.is_owner.assert_called_once_with(1)

    async def test_message_from_non_owner_returns_false(self):
        flt = self._make_filter()
        event = MagicMock(spec=Message)
        event.from_user = SimpleNamespace(id=2)
        with patch("bot.filters.admin.settings") as mock_settings:
            mock_settings.is_owner.return_value = False
            result = await flt(event)
        assert result is False

    async def test_callback_query_from_owner_returns_true(self):
        flt = self._make_filter()
        event = MagicMock(spec=CallbackQuery)
        event.from_user = SimpleNamespace(id=1)
        with patch("bot.filters.admin.settings") as mock_settings:
            mock_settings.is_owner.return_value = True
            result = await flt(event)
        assert result is True

    async def test_message_without_from_user_returns_false(self):
        flt = self._make_filter()
        event = MagicMock(spec=Message)
        event.from_user = None
        with patch("bot.filters.admin.settings") as mock_settings:
            result = await flt(event)
        assert result is False
        mock_settings.is_owner.assert_not_called()

    async def test_non_message_telegram_object_returns_false(self):
        flt = self._make_filter()
        event = MagicMock(spec=TelegramObject)
        with patch("bot.filters.admin.settings") as mock_settings:
            result = await flt(event)
        assert result is False
        mock_settings.is_owner.assert_not_called()


# ===========================================================================
# bot/constants/regions.py
# ===========================================================================


class TestRegionDataclass:
    """Tests for the Region frozen dataclass."""

    def test_region_has_code_and_name(self):
        from bot.constants.regions import Region

        r = Region(code="test", name="Тест")
        assert r.code == "test"
        assert r.name == "Тест"

    def test_region_is_frozen(self):
        from bot.constants.regions import Region

        r = Region(code="kyiv", name="Київ")
        with pytest.raises(FrozenInstanceError):
            r.code = "other"  # type: ignore[misc]


class TestRegionsDict:
    """Tests for the REGIONS constant."""

    def test_regions_has_exactly_four_entries(self):
        from bot.constants.regions import REGIONS

        assert len(REGIONS) == 4

    def test_regions_contains_expected_keys(self):
        from bot.constants.regions import REGIONS

        assert set(REGIONS.keys()) == {"kyiv", "kyiv-region", "dnipro", "odesa"}

    def test_each_key_matches_region_code(self):
        from bot.constants.regions import REGIONS

        for key, region in REGIONS.items():
            assert region.code == key

    def test_region_names_are_correct(self):
        from bot.constants.regions import REGIONS, Region

        assert REGIONS["kyiv"] == Region(code="kyiv", name="Київ")
        assert REGIONS["kyiv-region"] == Region(code="kyiv-region", name="Київщина")
        assert REGIONS["dnipro"] == Region(code="dnipro", name="Дніпропетровщина")
        assert REGIONS["odesa"] == Region(code="odesa", name="Одещина")

    def test_all_values_are_region_instances(self):
        from bot.constants.regions import REGIONS, Region

        for value in REGIONS.values():
            assert isinstance(value, Region)


class TestStandardQueues:
    """Tests for the STANDARD_QUEUES constant."""

    def test_has_twelve_entries(self):
        from bot.constants.regions import STANDARD_QUEUES

        assert len(STANDARD_QUEUES) == 12

    def test_first_element_is_1_1(self):
        from bot.constants.regions import STANDARD_QUEUES

        assert STANDARD_QUEUES[0] == "1.1"

    def test_last_element_is_6_2(self):
        from bot.constants.regions import STANDARD_QUEUES

        assert STANDARD_QUEUES[-1] == "6.2"

    def test_all_entries_match_expected_pattern(self):
        from bot.constants.regions import STANDARD_QUEUES

        import re

        pattern = re.compile(r"^[1-6]\.[12]$")
        for entry in STANDARD_QUEUES:
            assert pattern.match(entry)


class TestKyivExtraQueues:
    """Tests for the KYIV_EXTRA_QUEUES constant."""

    def test_has_54_entries(self):
        from bot.constants.regions import KYIV_EXTRA_QUEUES

        assert len(KYIV_EXTRA_QUEUES) == 54

    def test_first_element_is_7_1(self):
        from bot.constants.regions import KYIV_EXTRA_QUEUES

        assert KYIV_EXTRA_QUEUES[0] == "7.1"

    def test_last_element_is_60_1(self):
        from bot.constants.regions import KYIV_EXTRA_QUEUES

        assert KYIV_EXTRA_QUEUES[-1] == "60.1"


class TestKyivQueues:
    """Tests for the KYIV_QUEUES constant."""

    def test_has_66_entries(self):
        from bot.constants.regions import KYIV_QUEUES

        assert len(KYIV_QUEUES) == 66

    def test_is_standard_plus_extra(self):
        from bot.constants.regions import KYIV_EXTRA_QUEUES, KYIV_QUEUES, STANDARD_QUEUES

        assert KYIV_QUEUES == STANDARD_QUEUES + KYIV_EXTRA_QUEUES


class TestRegionQueues:
    """Tests for the REGION_QUEUES constant."""

    def test_contains_all_four_region_keys(self):
        from bot.constants.regions import REGION_QUEUES

        assert set(REGION_QUEUES.keys()) == {"kyiv", "kyiv-region", "dnipro", "odesa"}

    def test_kyiv_maps_to_kyiv_queues(self):
        from bot.constants.regions import KYIV_QUEUES, REGION_QUEUES

        assert REGION_QUEUES["kyiv"] is KYIV_QUEUES
        assert len(REGION_QUEUES["kyiv"]) == 66

    def test_other_regions_map_to_standard_queues(self):
        from bot.constants.regions import REGION_QUEUES, STANDARD_QUEUES

        for key in ("kyiv-region", "dnipro", "odesa"):
            assert REGION_QUEUES[key] is STANDARD_QUEUES
            assert len(REGION_QUEUES[key]) == 12


# ===========================================================================
# bot/handlers/schedule.py
# ===========================================================================


def _make_message(user_id: int | None = 123) -> AsyncMock:
    message = AsyncMock(spec=Message)
    if user_id is not None:
        message.from_user = SimpleNamespace(id=user_id)
    else:
        message.from_user = None
    message.answer = AsyncMock()
    message.answer_photo = AsyncMock()
    return message


def _make_session() -> AsyncMock:
    return AsyncMock()


_SCHEDULE_MODULE = "bot.handlers.schedule"


class TestCmdSchedule:
    """Tests for the /schedule command handler."""

    async def test_no_from_user_returns_early(self):
        from bot.handlers.schedule import cmd_schedule

        message = _make_message(user_id=None)
        session = _make_session()
        await cmd_schedule(message, session)
        message.answer.assert_not_awaited()
        message.answer_photo.assert_not_awaited()

    async def test_user_not_found_sends_start_message(self):
        from bot.handlers.schedule import cmd_schedule

        message = _make_message()
        session = _make_session()
        with patch(f"{_SCHEDULE_MODULE}.get_user_by_telegram_id", new_callable=AsyncMock, return_value=None):
            await cmd_schedule(message, session)
        message.answer.assert_awaited_once()
        assert "/start" in message.answer.call_args.args[0]

    async def test_fetch_data_none_sends_retry_message(self):
        from bot.handlers.schedule import cmd_schedule

        message = _make_message()
        session = _make_session()
        user = SimpleNamespace(region="kyiv", queue="1.1")
        with (
            patch(f"{_SCHEDULE_MODULE}.get_user_by_telegram_id", new_callable=AsyncMock, return_value=user),
            patch(f"{_SCHEDULE_MODULE}.fetch_schedule_data", new_callable=AsyncMock, return_value=None),
        ):
            await cmd_schedule(message, session)
        message.answer.assert_awaited_once()
        assert "Не вдалося" in message.answer.call_args.args[0]

    async def test_success_with_image_calls_answer_photo(self):
        from bot.handlers.schedule import cmd_schedule

        message = _make_message()
        session = _make_session()
        user = SimpleNamespace(region="kyiv", queue="1.1")
        image_bytes = b"fake_png_data"
        with (
            patch(f"{_SCHEDULE_MODULE}.get_user_by_telegram_id", new_callable=AsyncMock, return_value=user),
            patch(f"{_SCHEDULE_MODULE}.fetch_schedule_data", new_callable=AsyncMock, return_value={"raw": True}),
            patch(f"{_SCHEDULE_MODULE}.parse_schedule_for_queue", return_value={"parsed": True}),
            patch(f"{_SCHEDULE_MODULE}.format_schedule_message", return_value="<b>html</b>"),
            patch(f"{_SCHEDULE_MODULE}.get_schedule_view_keyboard", return_value=MagicMock()),
            patch(f"{_SCHEDULE_MODULE}.get_schedule_check_time", new_callable=AsyncMock, return_value=1234567890),
            patch(f"{_SCHEDULE_MODULE}.append_timestamp", return_value=("plain text", [])),
            patch(f"{_SCHEDULE_MODULE}.to_aiogram_entities", return_value=[]),
            patch(f"{_SCHEDULE_MODULE}.fetch_schedule_image", new_callable=AsyncMock, return_value=image_bytes),
        ):
            await cmd_schedule(message, session)
        message.answer_photo.assert_awaited_once()
        message.answer.assert_not_awaited()

    async def test_success_without_image_calls_answer(self):
        from bot.handlers.schedule import cmd_schedule

        message = _make_message()
        session = _make_session()
        user = SimpleNamespace(region="kyiv", queue="1.1")
        with (
            patch(f"{_SCHEDULE_MODULE}.get_user_by_telegram_id", new_callable=AsyncMock, return_value=user),
            patch(f"{_SCHEDULE_MODULE}.fetch_schedule_data", new_callable=AsyncMock, return_value={"raw": True}),
            patch(f"{_SCHEDULE_MODULE}.parse_schedule_for_queue", return_value={"parsed": True}),
            patch(f"{_SCHEDULE_MODULE}.format_schedule_message", return_value="<b>html</b>"),
            patch(f"{_SCHEDULE_MODULE}.get_schedule_view_keyboard", return_value=MagicMock()),
            patch(f"{_SCHEDULE_MODULE}.get_schedule_check_time", new_callable=AsyncMock, return_value=None),
            patch(f"{_SCHEDULE_MODULE}.append_timestamp", return_value=("plain text", [])),
            patch(f"{_SCHEDULE_MODULE}.to_aiogram_entities", return_value=[]),
            patch(f"{_SCHEDULE_MODULE}.fetch_schedule_image", new_callable=AsyncMock, return_value=None),
        ):
            await cmd_schedule(message, session)
        message.answer.assert_awaited_once()
        message.answer_photo.assert_not_awaited()


class TestCmdNext:
    """Tests for the /next command handler."""

    async def test_no_from_user_returns_early(self):
        from bot.handlers.schedule import cmd_next

        message = _make_message(user_id=None)
        session = _make_session()
        await cmd_next(message, session)
        message.answer.assert_not_awaited()

    async def test_user_not_found_sends_start_message(self):
        from bot.handlers.schedule import cmd_next

        message = _make_message()
        session = _make_session()
        with patch(f"{_SCHEDULE_MODULE}.get_user_by_telegram_id", new_callable=AsyncMock, return_value=None):
            await cmd_next(message, session)
        message.answer.assert_awaited_once()
        assert "/start" in message.answer.call_args.args[0]

    async def test_fetch_data_none_sends_retry_message(self):
        from bot.handlers.schedule import cmd_next

        message = _make_message()
        session = _make_session()
        user = SimpleNamespace(region="kyiv", queue="1.1")
        with (
            patch(f"{_SCHEDULE_MODULE}.get_user_by_telegram_id", new_callable=AsyncMock, return_value=user),
            patch(f"{_SCHEDULE_MODULE}.fetch_schedule_data", new_callable=AsyncMock, return_value=None),
        ):
            await cmd_next(message, session)
        message.answer.assert_awaited_once()
        assert "Не вдалося" in message.answer.call_args.args[0]

    async def test_success_calls_answer_with_html(self):
        from bot.handlers.schedule import cmd_next

        message = _make_message()
        session = _make_session()
        user = SimpleNamespace(region="kyiv", queue="1.1")
        with (
            patch(f"{_SCHEDULE_MODULE}.get_user_by_telegram_id", new_callable=AsyncMock, return_value=user),
            patch(f"{_SCHEDULE_MODULE}.fetch_schedule_data", new_callable=AsyncMock, return_value={"raw": True}),
            patch(f"{_SCHEDULE_MODULE}.parse_schedule_for_queue", return_value={"parsed": True}),
            patch(f"{_SCHEDULE_MODULE}.find_next_event", return_value={"event": "off"}),
            patch(f"{_SCHEDULE_MODULE}.format_next_event_message", return_value="<b>next</b>"),
        ):
            await cmd_next(message, session)
        message.answer.assert_awaited_once_with("<b>next</b>", parse_mode="HTML")


class TestCmdTimer:
    """Tests for the /timer command handler."""

    async def test_no_from_user_returns_early(self):
        from bot.handlers.schedule import cmd_timer

        message = _make_message(user_id=None)
        session = _make_session()
        await cmd_timer(message, session)
        message.answer.assert_not_awaited()

    async def test_user_not_found_sends_start_message(self):
        from bot.handlers.schedule import cmd_timer

        message = _make_message()
        session = _make_session()
        with patch(f"{_SCHEDULE_MODULE}.get_user_by_telegram_id", new_callable=AsyncMock, return_value=None):
            await cmd_timer(message, session)
        message.answer.assert_awaited_once()
        assert "Спочатку" in message.answer.call_args.args[0]

    async def test_fetch_data_none_sends_retry_message(self):
        from bot.handlers.schedule import cmd_timer

        message = _make_message()
        session = _make_session()
        user = SimpleNamespace(region="kyiv", queue="1.1")
        with (
            patch(f"{_SCHEDULE_MODULE}.get_user_by_telegram_id", new_callable=AsyncMock, return_value=user),
            patch(f"{_SCHEDULE_MODULE}.fetch_schedule_data", new_callable=AsyncMock, return_value=None),
        ):
            await cmd_timer(message, session)
        message.answer.assert_awaited_once()
        assert "Не вдалося" in message.answer.call_args.args[0]

    async def test_success_calls_answer_with_html(self):
        from bot.handlers.schedule import cmd_timer

        message = _make_message()
        session = _make_session()
        user = SimpleNamespace(region="kyiv", queue="1.1")
        with (
            patch(f"{_SCHEDULE_MODULE}.get_user_by_telegram_id", new_callable=AsyncMock, return_value=user),
            patch(f"{_SCHEDULE_MODULE}.fetch_schedule_data", new_callable=AsyncMock, return_value={"raw": True}),
            patch(f"{_SCHEDULE_MODULE}.parse_schedule_for_queue", return_value={"parsed": True}),
            patch(f"{_SCHEDULE_MODULE}.find_next_event", return_value={"event": "off"}),
            patch(f"{_SCHEDULE_MODULE}.format_timer_message", return_value="<b>timer</b>"),
        ):
            await cmd_timer(message, session)
        message.answer.assert_awaited_once_with("<b>timer</b>", parse_mode="HTML")
