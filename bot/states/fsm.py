from aiogram.fsm.state import State, StatesGroup


class WizardSG(StatesGroup):
    region = State()
    queue = State()
    notify_target = State()
    bot_notifications = State()
    channel_setup = State()
    channel_notifications = State()
    confirm = State()


class ChannelConversationSG(StatesGroup):
    waiting_for_title = State()
    waiting_for_description_choice = State()
    waiting_for_description = State()
    editing_title = State()
    editing_description = State()
    waiting_for_schedule_caption = State()
    waiting_for_period_format = State()
    waiting_for_power_off_text = State()
    waiting_for_power_on_text = State()
    waiting_for_custom_test = State()
    waiting_for_pause_message = State()


class IpSetupSG(StatesGroup):
    waiting_for_ip = State()


class BroadcastSG(StatesGroup):
    waiting_for_text = State()
    waiting_for_emoji = State()
    waiting_for_buttons = State()
    waiting_for_callback_button_text = State()
    waiting_for_callback_button_data = State()
    waiting_for_url_button_text = State()
    waiting_for_url_button_url = State()
    preview = State()


class MaintenanceSG(StatesGroup):
    waiting_for_message = State()


class AdminRouterIpSG(StatesGroup):
    waiting_for_ip = State()


class EmergencySetupSG(StatesGroup):
    waiting_for_city = State()    # only for non-Kyiv regions
    waiting_for_street = State()
    waiting_for_house = State()


class AddressCheckSG(StatesGroup):
    waiting_for_region = State()
    waiting_for_address = State()  # single message: "City, Street, House" or "Street, House"
