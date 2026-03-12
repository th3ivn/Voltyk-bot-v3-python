from aiogram.fsm.state import State, StatesGroup


class WizardStates(StatesGroup):
    region = State()
    queue = State()
    notify_target = State()
    channel_setup = State()
    confirm = State()
