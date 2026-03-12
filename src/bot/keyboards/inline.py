from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.bot.constants import REGIONS, get_queues_for_region, QUEUES

KYIV_MAX_PAGES = 5


# ──────────────────── Main Menu ────────────────────

def get_main_menu(
    bot_status: str = "active",
    channel_paused: bool = False,
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="Графік", callback_data="menu_schedule"),
            InlineKeyboardButton(text="Допомога", callback_data="menu_help"),
        ],
        [
            InlineKeyboardButton(text="Статистика", callback_data="menu_stats"),
            InlineKeyboardButton(text="Таймер", callback_data="menu_timer"),
        ],
        [
            InlineKeyboardButton(text="Налаштування", callback_data="menu_settings"),
        ],
    ]

    if bot_status != "no_channel":
        if channel_paused:
            buttons.append([
                InlineKeyboardButton(
                    text="Відновити роботу каналу",
                    callback_data="channel_resume",
                ),
            ])
        else:
            buttons.append([
                InlineKeyboardButton(
                    text="Тимчасово зупинити канал",
                    callback_data="channel_pause",
                ),
            ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ──────────────────── Region Selection ────────────────────

def get_region_keyboard() -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []

    region_codes = list(REGIONS.keys())
    for i, code in enumerate(region_codes):
        row.append(
            InlineKeyboardButton(text=REGIONS[code].name, callback_data=f"region_{code}")
        )
        if len(row) == 2 or i == len(region_codes) - 1:
            buttons.append(row.copy())
            row.clear()

    buttons.append([
        InlineKeyboardButton(text="🏙 Запропонувати регіон", callback_data="region_request_start")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ──────────────────── Queue Selection (with Kyiv pagination) ────────────────────

def get_queue_keyboard(region: str | None = None, page: int = 1) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []

    if region == "kyiv" and (page < 1 or page > KYIV_MAX_PAGES):
        page = 1

    # Non-Kyiv regions: standard 12 queues, 3 per row
    if not region or region != "kyiv":
        queues = get_queues_for_region(region) if region else QUEUES
        row: list[InlineKeyboardButton] = []

        for i, q in enumerate(queues):
            row.append(InlineKeyboardButton(text=q, callback_data=f"queue_{q}"))
            if len(row) == 3 or i == len(queues) - 1:
                buttons.append(row.copy())
                row.clear()

        buttons.append([InlineKeyboardButton(text="← Назад", callback_data="back_to_region")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)

    # Kyiv: paginated
    kyiv_queues = get_queues_for_region("kyiv")

    if page == 1:
        # Page 1: 1.1—6.2 (12 queues, 4 per row)
        page_queues = kyiv_queues[:12]
        _add_queue_rows(buttons, page_queues, cols=4)
        buttons.append([
            InlineKeyboardButton(text="Інші черги →", callback_data="queue_page_2")
        ])
        buttons.append([
            InlineKeyboardButton(text="← Назад", callback_data="back_to_region")
        ])

    elif page == 2:
        # Page 2: 7.1—22.1 (16 queues, 4×4)
        page_queues = kyiv_queues[12:28]
        _add_queue_rows(buttons, page_queues, cols=4)
        buttons.append([
            InlineKeyboardButton(text="← Назад", callback_data="queue_page_1"),
            InlineKeyboardButton(text="Далі →", callback_data="queue_page_3"),
        ])

    elif page == 3:
        # Page 3: 23.1—38.1 (16 queues, 4×4)
        page_queues = kyiv_queues[28:44]
        _add_queue_rows(buttons, page_queues, cols=4)
        buttons.append([
            InlineKeyboardButton(text="← Назад", callback_data="queue_page_2"),
            InlineKeyboardButton(text="Далі →", callback_data="queue_page_4"),
        ])

    elif page == 4:
        # Page 4: 39.1—54.1 (16 queues, 4×4)
        page_queues = kyiv_queues[44:60]
        _add_queue_rows(buttons, page_queues, cols=4)
        buttons.append([
            InlineKeyboardButton(text="← Назад", callback_data="queue_page_3"),
            InlineKeyboardButton(text="Далі →", callback_data="queue_page_5"),
        ])

    elif page == 5:
        # Page 5: 55.1—60.1 (6 queues, last page)
        page_queues = kyiv_queues[60:66]
        _add_queue_rows(buttons, page_queues, cols=4)
        buttons.append([
            InlineKeyboardButton(text="← Назад", callback_data="queue_page_4")
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _add_queue_rows(
    buttons: list[list[InlineKeyboardButton]],
    queues: list[str],
    cols: int = 4,
) -> None:
    row: list[InlineKeyboardButton] = []
    for i, q in enumerate(queues):
        row.append(InlineKeyboardButton(text=q, callback_data=f"queue_{q}"))
        if len(row) == cols or i == len(queues) - 1:
            buttons.append(row.copy())
            row.clear()


# ──────────────────── Wizard Step 3: Notify Target ────────────────────

def get_wizard_notify_target_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 У цьому боті", callback_data="wizard_notify_bot")],
        [InlineKeyboardButton(text="📺 У Telegram-каналі", callback_data="wizard_notify_channel")],
    ])


# ──────────────────── Confirm Setup ────────────────────

def get_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✓ Підтвердити", callback_data="confirm_setup")],
        [InlineKeyboardButton(text="🔄 Змінити регіон", callback_data="back_to_region")],
        [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
    ])


# ──────────────────── Restoration (deactivated user) ────────────────────

def get_restoration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Відновити налаштування", callback_data="restore_profile")],
        [InlineKeyboardButton(text="🆕 Почати заново", callback_data="create_new_profile")],
    ])


# ──────────────────── Wizard in-progress ────────────────────

def get_wizard_in_progress_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Продовжити налаштування", callback_data="wizard_resume")],
        [InlineKeyboardButton(text="🔄 Почати заново", callback_data="wizard_restart")],
    ])
