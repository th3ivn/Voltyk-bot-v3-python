"""Tests for bot/handlers/menu/schedule.py.

Coverage targets (current: 22%):
- _send_schedule_photo: all branches (no data, with/without image, edit/new, exceptions)
- menu_schedule: user not found, happy path
- schedule_check: user not found, cooldown hit, cleanup, cap eviction,
  API failure, hash changed, no change
- change_queue: user not found, message.photo branch, text branch
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_user(region: str = "kyiv", queue: str = "1.1", **kwargs) -> SimpleNamespace:
    return SimpleNamespace(region=region, queue=queue, **kwargs)


def _make_callback(user_id: int = 111, data: str = "") -> MagicMock:
    cb = MagicMock()
    cb.from_user = SimpleNamespace(id=user_id)
    cb.data = data
    cb.answer = AsyncMock()
    cb.message = MagicMock()
    cb.message.answer = AsyncMock()
    cb.message.answer_photo = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.message.edit_media = AsyncMock()
    cb.message.delete = AsyncMock()
    return cb


def _make_session() -> AsyncMock:
    return AsyncMock()


# ---------------------------------------------------------------------------
# _send_schedule_photo
# ---------------------------------------------------------------------------


class TestSendSchedulePhoto:
    async def test_data_none_answers_error(self):
        """Lines 42-46: fetch_schedule_data returns None → answer with error keyboard."""
        from bot.handlers.menu.schedule import _send_schedule_photo

        cb = _make_callback()
        user = _make_user()
        session = _make_session()

        with (
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value=None)),
        ):
            await _send_schedule_photo(cb, user, session)

        cb.message.answer.assert_called_once()
        assert "Щось пішло не так" in cb.message.answer.call_args[0][0]

    async def test_with_image_edit_photo_success(self):
        """Lines 60-65: image_bytes + edit_photo=True → edit_media called, returns early."""
        from bot.handlers.menu.schedule import _send_schedule_photo

        cb = _make_callback()
        user = _make_user()
        session = _make_session()

        with (
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"d": "x"})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={}),
            patch("bot.handlers.menu.schedule.format_schedule_message", return_value="<b>msg</b>"),
            patch("bot.handlers.menu.schedule.get_schedule_check_time", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.append_timestamp", return_value=("plain", [])),
            patch("bot.handlers.menu.schedule.to_aiogram_entities", return_value=[]),
            patch("bot.handlers.menu.schedule.fetch_schedule_image", AsyncMock(return_value=b"imgdata")),
            patch("bot.handlers.menu.schedule.get_schedule_view_keyboard", return_value=MagicMock()),
        ):
            await _send_schedule_photo(cb, user, session, edit_photo=True)

        cb.message.edit_media.assert_called_once()
        cb.message.answer_photo.assert_not_called()

    async def test_with_image_edit_photo_not_modified(self):
        """Lines 67-68: edit_media raises MSG_NOT_MODIFIED → return silently."""
        from bot.handlers.menu.schedule import _send_schedule_photo
        from bot.utils.telegram import MSG_NOT_MODIFIED

        cb = _make_callback()
        cb.message.edit_media = AsyncMock(side_effect=Exception(MSG_NOT_MODIFIED))
        user = _make_user()
        session = _make_session()

        with (
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"d": "x"})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={}),
            patch("bot.handlers.menu.schedule.format_schedule_message", return_value="<b>msg</b>"),
            patch("bot.handlers.menu.schedule.get_schedule_check_time", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.append_timestamp", return_value=("plain", [])),
            patch("bot.handlers.menu.schedule.to_aiogram_entities", return_value=[]),
            patch("bot.handlers.menu.schedule.fetch_schedule_image", AsyncMock(return_value=b"imgdata")),
            patch("bot.handlers.menu.schedule.get_schedule_view_keyboard", return_value=MagicMock()),
        ):
            await _send_schedule_photo(cb, user, session, edit_photo=True)

        # Not-modified → silent return, no fallback
        cb.message.answer_photo.assert_not_called()

    async def test_with_image_edit_photo_other_exception_fallback(self):
        """Lines 66-74: edit_media raises other error → fallback delete+send."""
        from bot.handlers.menu.schedule import _send_schedule_photo

        cb = _make_callback()
        cb.message.edit_media = AsyncMock(side_effect=Exception("some other error"))
        user = _make_user()
        session = _make_session()

        with (
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"d": "x"})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={}),
            patch("bot.handlers.menu.schedule.format_schedule_message", return_value="<b>msg</b>"),
            patch("bot.handlers.menu.schedule.get_schedule_check_time", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.append_timestamp", return_value=("plain", [])),
            patch("bot.handlers.menu.schedule.to_aiogram_entities", return_value=[]),
            patch("bot.handlers.menu.schedule.fetch_schedule_image", AsyncMock(return_value=b"imgdata")),
            patch("bot.handlers.menu.schedule.get_schedule_view_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.schedule.safe_delete", AsyncMock()),
        ):
            await _send_schedule_photo(cb, user, session, edit_photo=True)

        cb.message.answer_photo.assert_called_once()

    async def test_with_image_no_edit_photo_delete_send(self):
        """Lines 71-74: image_bytes + edit_photo=False → delete+answer_photo."""
        from bot.handlers.menu.schedule import _send_schedule_photo

        cb = _make_callback()
        user = _make_user()
        session = _make_session()

        with (
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"d": "x"})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={}),
            patch("bot.handlers.menu.schedule.format_schedule_message", return_value="<b>msg</b>"),
            patch("bot.handlers.menu.schedule.get_schedule_check_time", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.append_timestamp", return_value=("plain", [])),
            patch("bot.handlers.menu.schedule.to_aiogram_entities", return_value=[]),
            patch("bot.handlers.menu.schedule.fetch_schedule_image", AsyncMock(return_value=b"imgdata")),
            patch("bot.handlers.menu.schedule.get_schedule_view_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.schedule.safe_delete", AsyncMock()),
        ):
            await _send_schedule_photo(cb, user, session, edit_photo=False)

        cb.message.answer_photo.assert_called_once()

    async def test_no_image_edit_photo_success(self):
        """Lines 79-80: no image + edit_photo=True → edit_text, return early."""
        from bot.handlers.menu.schedule import _send_schedule_photo

        cb = _make_callback()
        user = _make_user()
        session = _make_session()

        with (
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"d": "x"})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={}),
            patch("bot.handlers.menu.schedule.format_schedule_message", return_value="<b>msg</b>"),
            patch("bot.handlers.menu.schedule.get_schedule_check_time", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.append_timestamp", return_value=("plain", [])),
            patch("bot.handlers.menu.schedule.to_aiogram_entities", return_value=[]),
            patch("bot.handlers.menu.schedule.fetch_schedule_image", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.get_schedule_view_keyboard", return_value=MagicMock()),
        ):
            await _send_schedule_photo(cb, user, session, edit_photo=True)

        cb.message.edit_text.assert_called_once()

    async def test_no_image_edit_photo_not_modified(self):
        """Lines 82-83: no image + edit_text raises MSG_NOT_MODIFIED → silent return."""
        from bot.handlers.menu.schedule import _send_schedule_photo
        from bot.utils.telegram import MSG_NOT_MODIFIED

        cb = _make_callback()
        cb.message.edit_text = AsyncMock(side_effect=Exception(MSG_NOT_MODIFIED))
        user = _make_user()
        session = _make_session()

        with (
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"d": "x"})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={}),
            patch("bot.handlers.menu.schedule.format_schedule_message", return_value="<b>msg</b>"),
            patch("bot.handlers.menu.schedule.get_schedule_check_time", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.append_timestamp", return_value=("plain", [])),
            patch("bot.handlers.menu.schedule.to_aiogram_entities", return_value=[]),
            patch("bot.handlers.menu.schedule.fetch_schedule_image", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.get_schedule_view_keyboard", return_value=MagicMock()),
        ):
            await _send_schedule_photo(cb, user, session, edit_photo=True)

        cb.message.answer.assert_not_called()

    async def test_no_image_edit_photo_other_exception_fallback(self):
        """Lines 81-86: no image + edit_text raises other error → fallback delete+send."""
        from bot.handlers.menu.schedule import _send_schedule_photo

        cb = _make_callback()
        cb.message.edit_text = AsyncMock(side_effect=Exception("network error"))
        user = _make_user()
        session = _make_session()

        with (
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"d": "x"})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={}),
            patch("bot.handlers.menu.schedule.format_schedule_message", return_value="<b>msg</b>"),
            patch("bot.handlers.menu.schedule.get_schedule_check_time", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.append_timestamp", return_value=("plain", [])),
            patch("bot.handlers.menu.schedule.to_aiogram_entities", return_value=[]),
            patch("bot.handlers.menu.schedule.fetch_schedule_image", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.get_schedule_view_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.schedule.safe_delete", AsyncMock()),
        ):
            await _send_schedule_photo(cb, user, session, edit_photo=True)

        cb.message.answer.assert_called_once()

    async def test_no_image_no_edit_photo_delete_send(self):
        """Line 85-86: no image + edit_photo=False → delete+answer (text)."""
        from bot.handlers.menu.schedule import _send_schedule_photo

        cb = _make_callback()
        user = _make_user()
        session = _make_session()

        with (
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"d": "x"})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={}),
            patch("bot.handlers.menu.schedule.format_schedule_message", return_value="<b>msg</b>"),
            patch("bot.handlers.menu.schedule.get_schedule_check_time", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.append_timestamp", return_value=("plain", [])),
            patch("bot.handlers.menu.schedule.to_aiogram_entities", return_value=[]),
            patch("bot.handlers.menu.schedule.fetch_schedule_image", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.get_schedule_view_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.schedule.safe_delete", AsyncMock()),
        ):
            await _send_schedule_photo(cb, user, session, edit_photo=False)

        cb.message.answer.assert_called_once()


# ---------------------------------------------------------------------------
# menu_schedule
# ---------------------------------------------------------------------------


class TestMenuSchedule:
    async def test_user_not_found_edits_error(self):
        """Lines 93-95: user=None → safe_edit_text with error message."""
        from bot.handlers.menu.schedule import menu_schedule

        cb = _make_callback()
        session = _make_session()

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=None)),
            patch("bot.handlers.menu.schedule.safe_edit_text", AsyncMock()) as mock_edit,
        ):
            await menu_schedule(cb, session)

        mock_edit.assert_called_once()

    async def test_user_found_sends_schedule(self):
        """Lines 91-96: user found → answer() + _send_schedule_photo called."""
        from bot.handlers.menu.schedule import menu_schedule

        cb = _make_callback()
        session = _make_session()
        user = _make_user()

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule._send_schedule_photo", AsyncMock()) as mock_send,
        ):
            await menu_schedule(cb, session)

        cb.answer.assert_called_once()
        mock_send.assert_called_once_with(cb, user, session, edit_photo=True)


# ---------------------------------------------------------------------------
# schedule_check
# ---------------------------------------------------------------------------


class TestScheduleCheck:
    def setup_method(self):
        # Reset module-level state before each test
        import bot.handlers.menu.schedule as m

        m._user_last_check.clear()
        m._last_check_cleanup_at = 0.0

    def teardown_method(self):
        import bot.handlers.menu.schedule as m

        m._user_last_check.clear()
        m._last_check_cleanup_at = 0.0

    async def test_user_not_found_answers_error(self):
        """Lines 103-105: user=None → callback.answer with error."""
        from bot.handlers.menu.schedule import schedule_check

        cb = _make_callback()
        session = _make_session()

        with patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await schedule_check(cb, session)

        cb.answer.assert_called_once()
        assert "Користувача не знайдено" in cb.answer.call_args[0][0]

    async def test_cooldown_active_answers_wait(self):
        """Lines 124-127: elapsed < cooldown → answer 'wait N sec'."""
        import bot.handlers.menu.schedule as m
        from bot.handlers.menu.schedule import schedule_check

        cb = _make_callback(user_id=200)
        session = _make_session()
        user = _make_user()

        # Simulate user just checked (now - 5s, cooldown=30)
        m._user_last_check[200] = time.monotonic() - 5

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule.get_setting", AsyncMock(return_value="30")),
        ):
            await schedule_check(cb, session)

        cb.answer.assert_called_once()
        assert "Зачекай" in cb.answer.call_args[0][0]

    async def test_cooldown_setting_invalid_uses_default(self):
        """Lines 110-111: get_setting returns non-int → use _DEFAULT_COOLDOWN_S."""
        from bot.handlers.menu.schedule import schedule_check

        cb = _make_callback(user_id=201)
        session = _make_session()
        user = _make_user()

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule.get_setting", AsyncMock(return_value="not-a-number")),
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"d": "x"})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={"events": []}),
            patch("bot.handlers.menu.schedule.calculate_schedule_hash", return_value="abc"),
            patch("bot.handlers.menu.schedule._send_schedule_photo", AsyncMock()),
        ):
            await schedule_check(cb, session)

        # Should not have raised, cooldown defaulted to 30s
        cb.answer.assert_called()

    async def test_periodic_cleanup_runs(self):
        """Lines 115-120: now - _last_check_cleanup_at > interval → cleanup stale entries."""
        import bot.handlers.menu.schedule as m
        from bot.handlers.menu.schedule import schedule_check

        cb = _make_callback(user_id=202)
        session = _make_session()
        user = _make_user()

        # Add stale entry and set cleanup timer far enough in the past to force cleanup.
        # Use now-based offset so the condition holds even on fast CI containers
        # where time.monotonic() may be < _LAST_CHECK_CLEANUP_INTERVAL (300s).
        now = time.monotonic()
        m._user_last_check[9999] = now - 10000  # stale: older than any cooldown
        m._last_check_cleanup_at = now - m._LAST_CHECK_CLEANUP_INTERVAL - 1

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule.get_setting", AsyncMock(return_value="30")),
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"d": "x"})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={"events": []}),
            patch("bot.handlers.menu.schedule.calculate_schedule_hash", return_value="abc"),
            patch("bot.handlers.menu.schedule._send_schedule_photo", AsyncMock()),
        ):
            await schedule_check(cb, session)

        # Stale entry should have been evicted
        assert 9999 not in m._user_last_check

    async def test_api_failure_clears_cooldown(self):
        """Lines 161-165: new_data=None → pop cooldown, answer error."""
        import bot.handlers.menu.schedule as m
        from bot.handlers.menu.schedule import schedule_check

        cb = _make_callback(user_id=203)
        session = _make_session()
        user = _make_user()

        # Pre-populate user's last check far in the past so elapsed >> cooldown_s,
        # regardless of how small monotonic() is in a fresh CI container.
        m._user_last_check[203] = time.monotonic() - 10000

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule.get_setting", AsyncMock(return_value="30")),
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(side_effect=[{"d": "x"}, None])),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={"events": []}),
            patch("bot.handlers.menu.schedule.calculate_schedule_hash", return_value=None),
        ):
            await schedule_check(cb, session)

        cb.answer.assert_called()
        assert "Не вдалось" in cb.answer.call_args[0][0]

    async def test_hash_changed_sends_update_and_answers(self):
        """Lines 171-173: old_hash != new_hash → send + answer 'знайдено зміни'."""
        import bot.handlers.menu.schedule as m
        from bot.handlers.menu.schedule import schedule_check

        cb = _make_callback(user_id=204)
        session = _make_session()
        user = _make_user()

        # Bypass cooldown in fresh CI containers where monotonic() < cooldown_s.
        m._user_last_check[204] = time.monotonic() - 10000

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule.get_setting", AsyncMock(return_value="30")),
            patch(
                "bot.handlers.menu.schedule.fetch_schedule_data",
                AsyncMock(side_effect=[{"old": True}, {"new": True}]),
            ),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={"events": ["e1"]}),
            patch(
                "bot.handlers.menu.schedule.calculate_schedule_hash",
                side_effect=["hash_old", "hash_new"],
            ),
            patch("bot.handlers.menu.schedule._send_schedule_photo", AsyncMock()),
        ):
            await schedule_check(cb, session)

        cb.answer.assert_called_once()
        assert "Знайдено зміни" in cb.answer.call_args[0][0]

    async def test_no_hash_change_sends_update_and_answers(self):
        """Lines 174-176: old_hash == new_hash → send + answer 'без змін'."""
        import bot.handlers.menu.schedule as m
        from bot.handlers.menu.schedule import schedule_check

        cb = _make_callback(user_id=205)
        session = _make_session()
        user = _make_user()

        # Bypass cooldown in fresh CI containers where monotonic() < cooldown_s.
        m._user_last_check[205] = time.monotonic() - 10000

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule.get_setting", AsyncMock(return_value="30")),
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"d": "x"})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={"events": ["e1"]}),
            patch("bot.handlers.menu.schedule.calculate_schedule_hash", return_value="same_hash"),
            patch("bot.handlers.menu.schedule._send_schedule_photo", AsyncMock()),
        ):
            await schedule_check(cb, session)

        cb.answer.assert_called_once()
        assert "Без змін" in cb.answer.call_args[0][0]

    async def test_cap_eviction_stale_entries_logged(self):
        """Lines 135-142: at cap with stale entries → batch-evict + debug log."""
        import bot.handlers.menu.schedule as m
        from bot.handlers.menu.schedule import _USER_LAST_CHECK_MAX_SIZE, schedule_check

        cb = _make_callback(user_id=99998)
        session = _make_session()
        user = _make_user()

        now = time.monotonic()
        # Disable periodic cleanup so it doesn't eat stale entries before cap block.
        m._last_check_cleanup_at = now
        # Pre-populate user 99998 far in the past so elapsed >> cooldown_s.
        # This is needed in fresh CI containers where monotonic() < cooldown (30s),
        # which would otherwise trigger the cooldown check before reaching cap eviction.
        m._user_last_check[99998] = now - 10000
        # Fill remaining slots to reach the cap (cap-1 more entries).
        half = _USER_LAST_CHECK_MAX_SIZE // 2
        for i in range(half):
            m._user_last_check[i] = now          # recent
        for i in range(half, _USER_LAST_CHECK_MAX_SIZE - 1):
            m._user_last_check[i] = now - 10000  # stale (older than cooldown)

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule.get_setting", AsyncMock(return_value="30")),
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"d": "x"})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={"events": []}),
            patch("bot.handlers.menu.schedule.calculate_schedule_hash", return_value=None),
            patch("bot.handlers.menu.schedule._send_schedule_photo", AsyncMock()),
        ):
            await schedule_check(cb, session)

        # Stale half should be evicted
        for i in range(half, _USER_LAST_CHECK_MAX_SIZE):
            assert i not in m._user_last_check

    async def test_cap_eviction_force_oldest_when_no_stale(self):
        """Lines 144-151: at cap, no stale entries → force-evict oldest 10%."""
        import bot.handlers.menu.schedule as m
        from bot.handlers.menu.schedule import _USER_LAST_CHECK_MAX_SIZE, schedule_check

        cb = _make_callback(user_id=99999)
        session = _make_session()
        user = _make_user()

        now = time.monotonic()
        # Disable periodic cleanup so cap block is reached.
        m._last_check_cleanup_at = now
        # Pre-populate user 99999 far in the past so elapsed >> cooldown_s.
        # This is needed in fresh CI containers where monotonic() < cooldown (30s).
        # After the single stale entry (99999) is evicted the dict is still at cap
        # (10000 fresh entries), which triggers the force-evict-oldest-10% block.
        m._user_last_check[99999] = now - 10000
        # Fill 0..(cap-1) with ALL fresh entries → stale_uids = [99999] only.
        for i in range(_USER_LAST_CHECK_MAX_SIZE):
            m._user_last_check[i] = now  # all fresh (0..9999)

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule.get_setting", AsyncMock(return_value="30")),
            patch("bot.handlers.menu.schedule.fetch_schedule_data", AsyncMock(return_value={"d": "x"})),
            patch("bot.handlers.menu.schedule.parse_schedule_for_queue", return_value={"events": []}),
            patch("bot.handlers.menu.schedule.calculate_schedule_hash", return_value=None),
            patch("bot.handlers.menu.schedule._send_schedule_photo", AsyncMock()),
        ):
            await schedule_check(cb, session)

        # Oldest 10% (1000 entries) evicted + user 99999 added → size < original cap
        assert len(m._user_last_check) < _USER_LAST_CHECK_MAX_SIZE


# ---------------------------------------------------------------------------
# change_queue
# ---------------------------------------------------------------------------


class TestChangeQueue:
    async def test_user_not_found_returns_early(self):
        """Lines 183-184: user=None → return without further action."""
        from bot.handlers.menu.schedule import change_queue

        cb = _make_callback()
        state = AsyncMock()
        session = _make_session()

        with patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=None)):
            await change_queue(cb, state, session)

        state.set_state.assert_not_called()

    async def test_message_has_photo_delete_and_answer(self):
        """Lines 189-191: message.photo is truthy → safe_delete + answer."""
        from bot.handlers.menu.schedule import change_queue

        cb = _make_callback()
        cb.message.photo = [MagicMock()]  # truthy
        state = AsyncMock()
        session = _make_session()
        user = _make_user()

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule.get_region_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.schedule.safe_delete", AsyncMock()) as mock_delete,
        ):
            await change_queue(cb, state, session)

        mock_delete.assert_called_once()
        cb.message.answer.assert_called_once()

    async def test_message_no_photo_safe_edit_text(self):
        """Lines 192-193: message.photo is falsy → safe_edit_text."""
        from bot.handlers.menu.schedule import change_queue

        cb = _make_callback()
        cb.message.photo = []  # falsy
        state = AsyncMock()
        session = _make_session()
        user = _make_user()

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule.get_region_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.schedule.safe_edit_text", AsyncMock()) as mock_edit,
        ):
            await change_queue(cb, state, session)

        mock_edit.assert_called_once()

    async def test_sets_wizard_state_and_mode(self):
        """Lines 186-187: state set to WizardSG.region + mode='edit_from_schedule'."""
        from bot.handlers.menu.schedule import change_queue
        from bot.states.fsm import WizardSG

        cb = _make_callback()
        cb.message.photo = []
        state = AsyncMock()
        session = _make_session()
        user = _make_user()

        with (
            patch("bot.handlers.menu.schedule.get_user_by_telegram_id", AsyncMock(return_value=user)),
            patch("bot.handlers.menu.schedule.get_region_keyboard", return_value=MagicMock()),
            patch("bot.handlers.menu.schedule.safe_edit_text", AsyncMock()),
        ):
            await change_queue(cb, state, session)

        state.set_state.assert_called_once_with(WizardSG.region)
        state.update_data.assert_called_once_with(mode="edit_from_schedule")
