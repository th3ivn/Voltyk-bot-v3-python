from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from bot.keyboards.common import E_REFRESH, E_REGION, _btn


def get_schedule_view_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("Замінити", "my_queues", E_REGION),
            _btn("Перевірити", "schedule_check", E_REFRESH),
        ],
        [_btn("⤴ Меню", "back_to_main")],
    ])
