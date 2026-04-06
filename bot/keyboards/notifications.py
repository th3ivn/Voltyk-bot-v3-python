from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from bot.keyboards.common import (
    E_BOT_NOTIF,
    E_CHANNEL,
    E_FACT,
    E_SCHEDULE_CHANGES,
    E_SCHEDULE_SEC,
    E_SUCCESS,
    _btn,
)


def _notif_keyboard(
    prefix: str,
    schedule_changes: bool, fact_off: bool,
    remind_15m: bool, remind_30m: bool, remind_1h: bool,
    back_cb: str, done_cb: str | None = None,
) -> InlineKeyboardMarkup:
    def _s(v: bool) -> str:
        return "success" if v else "default"

    rows = [
        [_btn("Оновлення графіків", f"{prefix}_toggle_schedule", E_SCHEDULE_CHANGES, style=_s(schedule_changes))],
        [
            _btn("1 год", f"{prefix}_time_60", style=_s(remind_1h)),
            _btn("30 хв", f"{prefix}_time_30", style=_s(remind_30m)),
            _btn("15 хв", f"{prefix}_time_15", style=_s(remind_15m)),
        ],
        [_btn("Фактично за IP-адресою", f"{prefix}_toggle_fact", E_FACT, style=_s(fact_off))],
    ]
    last_row = [_btn("← Назад", back_cb)]
    if done_cb:
        last_row.append(_btn("✓ Готово!", done_cb))
    rows.append(last_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_reminder_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        _btn("Графік", "reminder_show_schedule", E_SCHEDULE_SEC),
        _btn("Зрозуміло", "reminder_dismiss", E_SUCCESS),
    ]])


def get_notification_main_keyboard(
    schedule_changes: bool = True,
    remind_off: bool = True,
    fact_off: bool = True,
    remind_on: bool = True,
    fact_on: bool = True,
    remind_15m: bool = True,
    remind_30m: bool = False,
    remind_1h: bool = False,
    has_channel: bool = False,
    back_cb: str = "back_to_settings",
) -> InlineKeyboardMarkup:
    def _s(v: bool) -> str:
        return "success" if v else "default"

    rows = [
        [_btn("Оновлення графіків", "notif_toggle_schedule", E_SCHEDULE_CHANGES, style=_s(schedule_changes))],
        [
            _btn("1 год", "notif_time_60", style=_s(remind_1h)),
            _btn("30 хв", "notif_time_30", style=_s(remind_30m)),
            _btn("15 хв", "notif_time_15", style=_s(remind_15m)),
        ],
        [_btn("Фактично за IP-адресою", "notif_toggle_fact_off", E_FACT, style=_s(fact_off))],
    ]
    if has_channel:
        rows.append([_btn("📍 Куди надсилати  →", "notif_targets")])
    rows.append([_btn("← Назад", back_cb), _btn("⤴ Меню", "back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_notification_reminders_keyboard(**kw) -> InlineKeyboardMarkup:
    def _t(v: bool) -> str | None:
        return "success" if v else "danger"

    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🔴 Нагадування перед відкл.", "notif_toggle_remind_off", style=_t(kw.get("remind_off", True)))],
        [_btn("🔴 Факт відключення", "notif_toggle_fact_off", style=_t(kw.get("fact_off", True)))],
        [_btn("🟢 Нагадування перед вкл.", "notif_toggle_remind_on", style=_t(kw.get("remind_on", True)))],
        [_btn("🟢 Факт включення", "notif_toggle_fact_on", style=_t(kw.get("fact_on", True)))],
        [
            _btn("15 хв", "notif_time_15", style="success" if kw.get("remind_15m", True) else None),
            _btn("30 хв", "notif_time_30", style="success" if kw.get("remind_30m", False) else None),
            _btn("1 год", "notif_time_60", style="success" if kw.get("remind_1h", False) else None),
        ],
        [_btn("← Назад", "notif_main")],
    ])


def get_notification_targets_keyboard(has_ip: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [_btn("📊 Зміни графіка  →", "notif_target_type_schedule")],
        [_btn("⏰ Нагадування  →", "notif_target_type_remind")],
    ]
    if has_ip:
        rows.append([_btn("⚡ Факт. стан (IP)  →", "notif_target_type_power")])
    else:
        rows.append([_btn("📡 Налаштувати IP моніторинг", "settings_ip")])
    rows.append([_btn("← Назад", "notif_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_notification_target_select_keyboard(target_type: str, current_target: str = "bot") -> InlineKeyboardMarkup:
    def _m(t: str) -> str | None:
        return "success" if t == current_target else None

    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📱 В бот", f"notif_target_set_{target_type}_bot", style=_m("bot"))],
        [_btn("📺 В канал", f"notif_target_set_{target_type}_channel", style=_m("channel"))],
        [_btn("📱📺 Обидва", f"notif_target_set_{target_type}_both", style=_m("both"))],
        [_btn("← Назад", "notif_targets")],
    ])


def get_notification_select_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("Сповіщення в боті", "notif_select_bot", E_BOT_NOTIF)],
        [_btn("Сповіщення для каналу", "notif_select_channel", E_CHANNEL)],
        [_btn("← Назад", "back_to_main")],
    ])


def get_channel_notification_keyboard(**kw) -> InlineKeyboardMarkup:
    kb = _notif_keyboard("ch_notif", kw.get("schedule", True), kw.get("fact_off", True),
                         kw.get("remind_15m", True), kw.get("remind_30m", False), kw.get("remind_1h", False),
                         "notif_main")
    kb.inline_keyboard[-1].append(_btn("⤴ Меню", "back_to_main"))
    return kb
