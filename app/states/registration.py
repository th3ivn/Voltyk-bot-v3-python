"""FSM states for the user registration wizard."""

from aiogram.fsm.state import State, StatesGroup


class RegistrationFSM(StatesGroup):
    """States for the region/queue registration wizard."""

    choosing_region = State()
    choosing_queue = State()
    confirming = State()
