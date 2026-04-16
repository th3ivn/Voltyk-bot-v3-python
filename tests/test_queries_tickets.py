"""Tests for bot/db/queries/tickets.py — uses mocked AsyncSession."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.execute = AsyncMock()
    return session


def _scalars_first(value):
    scalars = MagicMock()
    scalars.first.return_value = value
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _scalars_all(items):
    scalars = MagicMock()
    scalars.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _scalar_result(value):
    result = MagicMock()
    result.scalar.return_value = value
    return result


# ---------------------------------------------------------------------------
# create_ticket
# ---------------------------------------------------------------------------


class TestCreateTicket:
    async def test_adds_ticket_and_flushes(self):
        """session.add() + flush() called; returns the new Ticket."""
        from bot.db.queries.tickets import create_ticket

        session = _make_session()

        result = await create_ticket(session, telegram_id="123", ticket_type="support")

        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert result is not None

    async def test_telegram_id_coerced_to_str(self):
        """int telegram_id is converted to str before setting on model."""
        from bot.db.queries.tickets import create_ticket

        session = _make_session()

        ticket = await create_ticket(session, telegram_id=42, ticket_type="bug")

        assert ticket.telegram_id == "42"

    async def test_subject_defaults_to_none(self):
        """subject parameter defaults to None."""
        from bot.db.queries.tickets import create_ticket

        session = _make_session()

        ticket = await create_ticket(session, telegram_id="1", ticket_type="other")

        assert ticket.subject is None

    async def test_subject_stored_when_provided(self):
        """Explicit subject is stored on the returned ticket."""
        from bot.db.queries.tickets import create_ticket

        session = _make_session()

        ticket = await create_ticket(session, telegram_id="1", ticket_type="other", subject="My issue")

        assert ticket.subject == "My issue"


# ---------------------------------------------------------------------------
# add_ticket_message
# ---------------------------------------------------------------------------


class TestAddTicketMessage:
    async def test_adds_message_and_flushes(self):
        """session.add() + flush() called; returns the new TicketMessage."""
        from bot.db.queries.tickets import add_ticket_message

        session = _make_session()

        msg = await add_ticket_message(session, ticket_id=1, sender_type="user", sender_id="111", content="Hello")

        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert msg is not None

    async def test_sender_id_coerced_to_str(self):
        """int sender_id is coerced to str."""
        from bot.db.queries.tickets import add_ticket_message

        session = _make_session()

        msg = await add_ticket_message(session, ticket_id=1, sender_type="admin", sender_id=99, content="Reply")

        assert msg.sender_id == "99"

    async def test_defaults(self):
        """content=None, file_id=None, message_type='text' by default."""
        from bot.db.queries.tickets import add_ticket_message

        session = _make_session()

        msg = await add_ticket_message(session, ticket_id=1, sender_type="user", sender_id="1")

        assert msg.content is None
        assert msg.file_id is None
        assert msg.message_type == "text"

    async def test_file_id_stored_when_provided(self):
        """Explicit file_id is stored on the returned message."""
        from bot.db.queries.tickets import add_ticket_message

        session = _make_session()

        msg = await add_ticket_message(
            session, ticket_id=1, sender_type="user", sender_id="1", file_id="FILEID", message_type="photo"
        )

        assert msg.file_id == "FILEID"
        assert msg.message_type == "photo"


# ---------------------------------------------------------------------------
# get_open_tickets
# ---------------------------------------------------------------------------


class TestGetOpenTickets:
    async def test_returns_list_of_open_tickets(self):
        """execute → scalars().all() returned as list."""
        from bot.db.queries.tickets import get_open_tickets

        session = _make_session()
        tickets = [SimpleNamespace(id=1, status="open"), SimpleNamespace(id=2, status="open")]
        session.execute.return_value = _scalars_all(tickets)

        result = await get_open_tickets(session)

        assert result == tickets
        session.execute.assert_called_once()

    async def test_returns_empty_list_when_none_open(self):
        """No open tickets → empty list."""
        from bot.db.queries.tickets import get_open_tickets

        session = _make_session()
        session.execute.return_value = _scalars_all([])

        result = await get_open_tickets(session)

        assert result == []


# ---------------------------------------------------------------------------
# get_all_tickets
# ---------------------------------------------------------------------------


class TestGetAllTickets:
    async def test_returns_all_tickets(self):
        """Returns all tickets regardless of status."""
        from bot.db.queries.tickets import get_all_tickets

        session = _make_session()
        tickets = [SimpleNamespace(id=1, status="open"), SimpleNamespace(id=2, status="closed")]
        session.execute.return_value = _scalars_all(tickets)

        result = await get_all_tickets(session)

        assert result == tickets
        session.execute.assert_called_once()

    async def test_returns_empty_list_when_no_tickets(self):
        """No tickets → empty list."""
        from bot.db.queries.tickets import get_all_tickets

        session = _make_session()
        session.execute.return_value = _scalars_all([])

        result = await get_all_tickets(session)

        assert result == []


# ---------------------------------------------------------------------------
# get_ticket_by_id
# ---------------------------------------------------------------------------


class TestGetTicketById:
    async def test_returns_ticket_when_found(self):
        """scalars().first() returns ticket → ticket returned."""
        from bot.db.queries.tickets import get_ticket_by_id

        session = _make_session()
        ticket = SimpleNamespace(id=7, status="open")
        session.execute.return_value = _scalars_first(ticket)

        result = await get_ticket_by_id(session, ticket_id=7)

        assert result is ticket
        session.execute.assert_called_once()

    async def test_returns_none_when_not_found(self):
        """scalars().first() returns None → None returned."""
        from bot.db.queries.tickets import get_ticket_by_id

        session = _make_session()
        session.execute.return_value = _scalars_first(None)

        result = await get_ticket_by_id(session, ticket_id=999)

        assert result is None


# ---------------------------------------------------------------------------
# close_ticket
# ---------------------------------------------------------------------------


class TestCloseTicket:
    async def test_execute_called_with_update(self):
        """UPDATE stmt executed to set status='closed'."""
        from bot.db.queries.tickets import close_ticket

        session = _make_session()

        await close_ticket(session, ticket_id=1, closed_by="admin")

        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# reopen_ticket
# ---------------------------------------------------------------------------


class TestReopenTicket:
    async def test_execute_called_with_update(self):
        """UPDATE stmt executed to set status='open'."""
        from bot.db.queries.tickets import reopen_ticket

        session = _make_session()

        await reopen_ticket(session, ticket_id=1)

        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# count_open_tickets
# ---------------------------------------------------------------------------


class TestCountOpenTickets:
    async def test_returns_count(self):
        """scalar() returns int → that int is returned."""
        from bot.db.queries.tickets import count_open_tickets

        session = _make_session()
        session.execute.return_value = _scalar_result(5)

        result = await count_open_tickets(session)

        assert result == 5
        session.execute.assert_called_once()

    async def test_returns_zero_when_scalar_none(self):
        """scalar() returns None (empty aggregation) → 0 returned."""
        from bot.db.queries.tickets import count_open_tickets

        session = _make_session()
        session.execute.return_value = _scalar_result(None)

        result = await count_open_tickets(session)

        assert result == 0
