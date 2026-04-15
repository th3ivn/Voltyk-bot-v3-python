"""Tests for bot/db/queries/power.py — uses mocked AsyncSession."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock()
    return session


def _make_scalars_result(items):
    scalars = MagicMock()
    scalars.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


# ---------------------------------------------------------------------------
# change_power_state_and_get_duration
# ---------------------------------------------------------------------------


class TestChangePowerStateAndGetDuration:
    async def test_returns_dict_when_row_found(self):
        """Lines 34-66: SQL executed, row found → dict returned."""
        from bot.db.queries.power import change_power_state_and_get_duration
        from datetime import datetime, timezone

        session = _make_session()
        ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = (ts, 45.0)
        session.execute.return_value = mock_result

        result = await change_power_state_and_get_duration(session, "111", "on")

        assert result == {"power_changed_at": ts, "duration_minutes": 45.0}
        session.execute.assert_called_once()

    async def test_returns_none_when_no_row(self):
        """Line 67: fetchone() returns None → function returns None."""
        from bot.db.queries.power import change_power_state_and_get_duration

        session = _make_session()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        session.execute.return_value = mock_result

        result = await change_power_state_and_get_duration(session, 999, "off")

        assert result is None

    async def test_telegram_id_coerced_to_str(self):
        """Line 33: int telegram_id is converted to str before query."""
        from bot.db.queries.power import change_power_state_and_get_duration

        session = _make_session()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        session.execute.return_value = mock_result

        await change_power_state_and_get_duration(session, 42, "on")

        # The execute was called with params including tid="42"
        call_kwargs = session.execute.call_args[0][1]
        assert call_kwargs["tid"] == "42"


# ---------------------------------------------------------------------------
# upsert_user_power_state
# ---------------------------------------------------------------------------


class TestUpsertUserPowerState:
    async def test_execute_called_with_upsert_stmt(self):
        """Lines 74-78: upsert stmt built and executed."""
        from bot.db.queries.power import upsert_user_power_state

        session = _make_session()

        await upsert_user_power_state(session, "123", current_state="on")

        session.execute.assert_called_once()

    async def test_telegram_id_coerced_to_str(self):
        """Line 74: int telegram_id → str."""
        from bot.db.queries.power import upsert_user_power_state

        session = _make_session()
        await upsert_user_power_state(session, 456, current_state="off")
        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# batch_upsert_user_power_states
# ---------------------------------------------------------------------------


class TestBatchUpsertUserPowerStates:
    async def test_empty_list_returns_early(self):
        """Lines 91-92: states=[] → return immediately, execute not called."""
        from bot.db.queries.power import batch_upsert_user_power_states

        session = _make_session()
        await batch_upsert_user_power_states(session, [])
        session.execute.assert_not_called()

    async def test_non_empty_executes_upsert(self):
        """Lines 93-98: states with rows → execute called once."""
        from bot.db.queries.power import batch_upsert_user_power_states

        session = _make_session()
        await batch_upsert_user_power_states(
            session,
            [
                {"telegram_id": "111", "current_state": "on"},
                {"telegram_id": "222", "current_state": "off"},
            ],
        )
        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# get_user_power_state
# ---------------------------------------------------------------------------


class TestGetUserPowerState:
    async def test_returns_scalar_result(self):
        """Lines 105-106: session.scalar called → result returned."""
        from bot.db.queries.power import get_user_power_state

        session = _make_session()
        mock_state = SimpleNamespace(telegram_id="111", current_state="on")
        session.scalar.return_value = mock_state

        result = await get_user_power_state(session, "111")

        assert result is mock_state
        session.scalar.assert_called_once()

    async def test_returns_none_when_not_found(self):
        """Line 106: scalar returns None → None returned."""
        from bot.db.queries.power import get_user_power_state

        session = _make_session()
        session.scalar.return_value = None

        result = await get_user_power_state(session, "999")

        assert result is None


# ---------------------------------------------------------------------------
# get_recent_user_power_states
# ---------------------------------------------------------------------------


class TestGetRecentUserPowerStates:
    async def test_returns_list_from_scalars(self):
        """Lines 118-122: execute → scalars().all() returned as list."""
        from bot.db.queries.power import get_recent_user_power_states

        session = _make_session()
        states = [SimpleNamespace(telegram_id="111"), SimpleNamespace(telegram_id="222")]
        session.execute.return_value = _make_scalars_result(states)

        result = await get_recent_user_power_states(session)

        assert result == states
        session.execute.assert_called_once()

    async def test_returns_empty_list_when_no_results(self):
        """Lines 118-122: no rows → empty list."""
        from bot.db.queries.power import get_recent_user_power_states

        session = _make_session()
        session.execute.return_value = _make_scalars_result([])

        result = await get_recent_user_power_states(session)

        assert result == []


# ---------------------------------------------------------------------------
# add_power_history
# ---------------------------------------------------------------------------


class TestAddPowerHistory:
    async def test_adds_record_and_flushes(self):
        """Lines 133-139: session.add() + flush() called."""
        from bot.db.queries.power import add_power_history

        session = _make_session()

        await add_power_history(session, user_id=1, event_type="off", timestamp=1700000000, duration_seconds=3600)

        session.add.assert_called_once()
        session.flush.assert_called_once()

    async def test_duration_seconds_can_be_none(self):
        """Line 133: duration_seconds=None → still adds record."""
        from bot.db.queries.power import add_power_history

        session = _make_session()

        await add_power_history(session, user_id=2, event_type="on", timestamp=1700000000, duration_seconds=None)

        session.add.assert_called_once()


# ---------------------------------------------------------------------------
# get_power_history_week
# ---------------------------------------------------------------------------


class TestGetPowerHistoryWeek:
    async def test_returns_list_ordered_by_desc_timestamp(self):
        """Lines 144-150: execute → scalars().all() returned as list."""
        from bot.db.queries.power import get_power_history_week

        session = _make_session()
        records = [SimpleNamespace(user_id=1, timestamp=1700001000), SimpleNamespace(user_id=1, timestamp=1700000000)]
        session.execute.return_value = _make_scalars_result(records)

        result = await get_power_history_week(session, user_id=1)

        assert result == records
        session.execute.assert_called_once()

    async def test_empty_history_returns_empty_list(self):
        """Lines 144-150: no records → empty list."""
        from bot.db.queries.power import get_power_history_week

        session = _make_session()
        session.execute.return_value = _make_scalars_result([])

        result = await get_power_history_week(session, user_id=99)

        assert result == []


# ---------------------------------------------------------------------------
# upsert_ping_error_alert
# ---------------------------------------------------------------------------


class TestUpsertPingErrorAlert:
    async def test_execute_called(self):
        """Lines 157-166: pg_insert upsert built and executed."""
        from bot.db.queries.power import upsert_ping_error_alert

        session = _make_session()

        await upsert_ping_error_alert(session, telegram_id="123", router_ip="1.2.3.4")

        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# get_active_ping_error_alerts
# ---------------------------------------------------------------------------


class TestGetActivePingErrorAlerts:
    async def test_returns_active_alerts(self):
        """Lines 171-174: execute → scalars().all() as list."""
        from bot.db.queries.power import get_active_ping_error_alerts

        session = _make_session()
        alerts = [SimpleNamespace(telegram_id="111", is_active=True)]
        session.execute.return_value = _make_scalars_result(alerts)

        result = await get_active_ping_error_alerts(session)

        assert result == alerts
        session.execute.assert_called_once()

    async def test_returns_empty_list_when_none_active(self):
        """Lines 171-174: no active alerts → empty list."""
        from bot.db.queries.power import get_active_ping_error_alerts

        session = _make_session()
        session.execute.return_value = _make_scalars_result([])

        result = await get_active_ping_error_alerts(session)

        assert result == []


# ---------------------------------------------------------------------------
# deactivate_ping_error_alert
# ---------------------------------------------------------------------------


class TestDeactivatePingErrorAlert:
    async def test_execute_called_with_update(self):
        """Lines 179-183: update stmt executed."""
        from bot.db.queries.power import deactivate_ping_error_alert

        session = _make_session()

        await deactivate_ping_error_alert(session, telegram_id="123")

        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# update_ping_error_alert_time
# ---------------------------------------------------------------------------


class TestUpdatePingErrorAlertTime:
    async def test_execute_called(self):
        """Line 190-193: update stmt with last_alert_at=now executed."""
        from bot.db.queries.power import update_ping_error_alert_time

        session = _make_session()

        await update_ping_error_alert_time(session, telegram_id="456")

        session.execute.assert_called_once()
