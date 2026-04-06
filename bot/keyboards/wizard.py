from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.constants.regions import KYIV_QUEUES, REGION_QUEUES, STANDARD_QUEUES
from bot.keyboards.common import _btn
from bot.keyboards.notifications import _notif_keyboard


def get_region_keyboard(current_region: str | None = None) -> InlineKeyboardMarkup:
    def _r(label: str, code: str) -> InlineKeyboardButton:
        selected = current_region == code
        return _btn(label, f"region_{code}", style="success" if selected else None)

    rows = [
        [_r("Київ", "kyiv"), _r("Київщина", "kyiv-region")],
        [_r("Дніпропетровщина", "dnipro"), _r("Одещина", "odesa")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_queue_keyboard(region: str, page: int = 1, current_queue: str | None = None) -> InlineKeyboardMarkup:
    queues = REGION_QUEUES.get(region, STANDARD_QUEUES)
    rows: list[list[InlineKeyboardButton]] = []

    def _q(q: str) -> InlineKeyboardButton:
        selected = current_queue == q
        return _btn(q, f"queue_{q}", style="success" if selected else None)

    if region != "kyiv":
        for i in range(0, len(queues), 3):
            row = [_q(q) for q in queues[i : i + 3]]
            rows.append(row)
        rows.append([_btn("← Назад", "back_to_region")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    pages: dict[int, list[str]] = {1: STANDARD_QUEUES}
    extra = KYIV_QUEUES[len(STANDARD_QUEUES) :]
    page_size = 16
    for idx, start in enumerate(range(0, len(extra), page_size)):
        pages[idx + 2] = extra[start : start + page_size]

    total_pages = len(pages)
    current_queues = pages.get(page, STANDARD_QUEUES)
    cols = 4

    for i in range(0, len(current_queues), cols):
        row = [_q(q) for q in current_queues[i : i + cols]]
        rows.append(row)

    if page == 1:
        rows.append([_btn("Інші черги →", "queue_page_2")])
        rows.append([_btn("← Назад", "back_to_region")])
    else:
        nav: list[InlineKeyboardButton] = []
        nav.append(_btn("← Назад", f"queue_page_{page - 1}"))
        if page < total_pages:
            nav.append(_btn("Далі →", f"queue_page_{page + 1}"))
        rows.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✓ Підтвердити", "confirm_setup")],
        [_btn("🔄 Змінити регіон", "back_to_region")],
        [_btn("⤴ Меню", "back_to_main")],
    ])


def get_wizard_notify_target_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📱 У цьому боті", "wizard_notify_bot")],
        [_btn("📺 У Telegram-каналі", "wizard_notify_channel")],
    ])


def get_wizard_bot_notification_keyboard(**kw) -> InlineKeyboardMarkup:
    return _notif_keyboard("wizard_notif", kw.get("schedule_changes", True), kw.get("fact_off", True),
                           kw.get("remind_15m", True), kw.get("remind_30m", False), kw.get("remind_1h", False),
                           "wizard_notify_back", "wizard_bot_done")


def get_wizard_channel_notification_keyboard(**kw) -> InlineKeyboardMarkup:
    return _notif_keyboard("wizard_ch_notif", kw.get("schedule_changes", True), kw.get("fact_off", True),
                           kw.get("remind_15m", True), kw.get("remind_30m", False), kw.get("remind_1h", False),
                           "wizard_channel_back", "wizard_channel_done")
