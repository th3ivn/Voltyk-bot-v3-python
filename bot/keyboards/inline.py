from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.constants.regions import KYIV_QUEUES, REGION_QUEUES, REGIONS, STANDARD_QUEUES


def get_main_menu(channel_paused: bool = False, has_channel: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="Графік", callback_data="menu_schedule"),
            InlineKeyboardButton(text="Допомога", callback_data="menu_help"),
        ],
        [
            InlineKeyboardButton(text="Статистика", callback_data="menu_stats"),
            InlineKeyboardButton(text="Таймер", callback_data="menu_timer"),
        ],
        [InlineKeyboardButton(text="Налаштування", callback_data="menu_settings")],
    ]
    if has_channel:
        if channel_paused:
            rows.append([InlineKeyboardButton(text="Відновити роботу каналу", callback_data="channel_resume")])
        else:
            rows.append(
                [InlineKeyboardButton(text="Тимчасово зупинити канал", callback_data="channel_pause")]
            )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_schedule_view_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Замінити", callback_data="my_queues"),
                InlineKeyboardButton(text="Оновити", callback_data="schedule_refresh"),
            ],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_region_keyboard() -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    region_list = list(REGIONS.values())
    for i in range(0, len(region_list), 2):
        row = [InlineKeyboardButton(text=r.name, callback_data=f"region_{r.code}") for r in region_list[i : i + 2]]
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="🏙 Запропонувати регіон", callback_data="region_request_start")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_queue_keyboard(region: str, page: int = 1) -> InlineKeyboardMarkup:
    queues = REGION_QUEUES.get(region, STANDARD_QUEUES)
    rows: list[list[InlineKeyboardButton]] = []

    if region != "kyiv":
        for i in range(0, len(queues), 3):
            row = [InlineKeyboardButton(text=q, callback_data=f"queue_{q}") for q in queues[i : i + 3]]
            rows.append(row)
        rows.append([InlineKeyboardButton(text="← Назад", callback_data="back_to_region")])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    pages: dict[int, list[str]] = {1: STANDARD_QUEUES}
    extra = KYIV_QUEUES[len(STANDARD_QUEUES) :]
    page_size = 16
    for idx, start in enumerate(range(0, len(extra), page_size)):
        pages[idx + 2] = extra[start : start + page_size]

    total_pages = len(pages)
    current_queues = pages.get(page, STANDARD_QUEUES)
    cols = 4 if page > 1 else 3

    for i in range(0, len(current_queues), cols):
        row = [InlineKeyboardButton(text=q, callback_data=f"queue_{q}") for q in current_queues[i : i + cols]]
        rows.append(row)

    nav_row: list[InlineKeyboardButton] = []
    if page == 1:
        nav_row.append(InlineKeyboardButton(text="Інші черги →", callback_data="queue_page_2"))
        nav_row.insert(0, InlineKeyboardButton(text="← Назад", callback_data="back_to_region"))
    else:
        nav_row.append(InlineKeyboardButton(text="← Назад", callback_data=f"queue_page_{page - 1}"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton(text="Далі →", callback_data=f"queue_page_{page + 1}"))
    rows.append(nav_row)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✓ Підтвердити", callback_data="confirm_setup")],
            [InlineKeyboardButton(text="🔄 Змінити регіон", callback_data="back_to_region")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_settings_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Регіон", callback_data="settings_region"),
            InlineKeyboardButton(text="IP", callback_data="settings_ip"),
        ],
        [
            InlineKeyboardButton(text="Канал", callback_data="settings_channel"),
            InlineKeyboardButton(text="Сповіщення", callback_data="settings_alerts"),
        ],
        [InlineKeyboardButton(text="🗑 Очищення", callback_data="settings_cleanup")],
    ]
    if is_admin:
        rows.append([InlineKeyboardButton(text="Адмін-панель", callback_data="settings_admin")])
    rows.extend([
        [InlineKeyboardButton(text="Видалити мої дані", callback_data="settings_delete_data")],
        [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_statistics_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⚡ Відключення за тиждень", callback_data="stats_week")],
            [InlineKeyboardButton(text="📡 Статус пристрою", callback_data="stats_device")],
            [InlineKeyboardButton(text="⚙️ Мої налаштування", callback_data="stats_settings")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_help_keyboard(support_url: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="📖 Інструкція", callback_data="help_howto")],
    ]
    if support_url:
        rows.append([InlineKeyboardButton(text="✉️ Підтримка", url=support_url)])
    else:
        rows.append([InlineKeyboardButton(text="⚒️ Підтримка", callback_data="feedback_start")])
    rows.extend([
        [InlineKeyboardButton(text="📢 Новини", url="https://t.me/Voltyk_news")],
        [InlineKeyboardButton(text="💬 Обговорення", url="https://t.me/voltyk_chat")],
        [InlineKeyboardButton(text="🏙 Запропонувати регіон", callback_data="region_request_start")],
        [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_channel_menu_keyboard(
    channel_id: str | None = None,
    is_public: bool = False,
    channel_username: str | None = None,
    channel_status: str = "active",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if not channel_id:
        rows.append([InlineKeyboardButton(text="✚ Підключити канал", callback_data="channel_connect")])
    else:
        if is_public and channel_username:
            rows.append(
                [InlineKeyboardButton(text="📺 Відкрити канал", url=f"https://t.me/{channel_username}")]
            )
        rows.append([
            InlineKeyboardButton(text="ℹ️ Інфо", callback_data="channel_info"),
            InlineKeyboardButton(text="✏️ Назва", callback_data="channel_edit_title"),
        ])
        rows.append([
            InlineKeyboardButton(text="📝 Опис", callback_data="channel_edit_description"),
            InlineKeyboardButton(text="📋 Формат", callback_data="channel_format"),
        ])
        rows.append([
            InlineKeyboardButton(text="🧪 Тест", callback_data="channel_test"),
        ])
        if channel_status == "blocked":
            rows.append([InlineKeyboardButton(text="⚙️ Перепідключити", callback_data="channel_reconnect")])
        else:
            rows.append([InlineKeyboardButton(text="🔴 Вимкнути", callback_data="channel_disable")])
        rows.append([InlineKeyboardButton(text="🔔 Сповіщення", callback_data="channel_notifications")])

    rows.extend([
        [InlineKeyboardButton(text="← Назад", callback_data="back_to_settings")],
        [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_restoration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Відновити налаштування", callback_data="restore_profile")],
            [InlineKeyboardButton(text="🆕 Почати заново", callback_data="create_new_profile")],
        ]
    )


def get_wizard_notify_target_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 У цьому боті", callback_data="wizard_notify_bot")],
            [InlineKeyboardButton(text="📺 У Telegram-каналі", callback_data="wizard_notify_channel")],
        ]
    )


def get_wizard_bot_notification_keyboard(
    schedule_changes: bool = True,
    remind_off: bool = True,
    fact_off: bool = True,
    remind_on: bool = True,
    fact_on: bool = True,
    remind_15m: bool = True,
    remind_30m: bool = False,
    remind_1h: bool = False,
) -> InlineKeyboardMarkup:
    def _check(v: bool) -> str:
        return "✅" if v else "❌"

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=f"Оновлення графіків {_check(schedule_changes)}", callback_data="wizard_notif_toggle_schedule")],
        [
            InlineKeyboardButton(text=f"1 год {_check(remind_1h)}", callback_data="wizard_notif_time_60"),
            InlineKeyboardButton(text=f"30 хв {_check(remind_30m)}", callback_data="wizard_notif_time_30"),
            InlineKeyboardButton(text=f"15 хв {_check(remind_15m)}", callback_data="wizard_notif_time_15"),
        ],
        [InlineKeyboardButton(
            text=f"Фактично за {'IP-адресою' if True else 'графіком'} {_check(fact_off)}",
            callback_data="wizard_notif_toggle_fact",
        )],
        [InlineKeyboardButton(text="← Назад", callback_data="wizard_notify_back")],
        [InlineKeyboardButton(text="✓ Готово!", callback_data="wizard_bot_done")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_wizard_channel_notification_keyboard(
    schedule_changes: bool = True,
    remind_off: bool = True,
    fact_off: bool = True,
    remind_on: bool = True,
    fact_on: bool = True,
    remind_15m: bool = True,
    remind_30m: bool = False,
    remind_1h: bool = False,
) -> InlineKeyboardMarkup:
    def _check(v: bool) -> str:
        return "✅" if v else "❌"

    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=f"Оновлення графіків {_check(schedule_changes)}", callback_data="wizard_ch_notif_toggle_schedule")],
        [
            InlineKeyboardButton(text=f"1 год {_check(remind_1h)}", callback_data="wizard_ch_notif_time_60"),
            InlineKeyboardButton(text=f"30 хв {_check(remind_30m)}", callback_data="wizard_ch_notif_time_30"),
            InlineKeyboardButton(text=f"15 хв {_check(remind_15m)}", callback_data="wizard_ch_notif_time_15"),
        ],
        [InlineKeyboardButton(
            text=f"Фактично за {'IP-адресою' if True else 'графіком'} {_check(fact_off)}",
            callback_data="wizard_ch_notif_toggle_fact",
        )],
        [InlineKeyboardButton(text="← Назад", callback_data="wizard_channel_back")],
        [InlineKeyboardButton(text="✓ Готово!", callback_data="wizard_channel_done")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_notification_main_keyboard(
    schedule_changes: bool = True,
) -> InlineKeyboardMarkup:
    def _check(v: bool) -> str:
        return "✅" if v else "❌"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"📊 Зміни графіка {_check(schedule_changes)}", callback_data="notif_toggle_schedule")],
            [InlineKeyboardButton(text="⏰ Нагадування →", callback_data="notif_reminders")],
            [InlineKeyboardButton(text="📍 Куди надсилати →", callback_data="notif_targets")],
            [InlineKeyboardButton(text="← Назад", callback_data="back_to_settings")],
        ]
    )


def get_notification_reminders_keyboard(
    remind_off: bool = True,
    fact_off: bool = True,
    remind_on: bool = True,
    fact_on: bool = True,
    remind_15m: bool = True,
    remind_30m: bool = False,
    remind_1h: bool = False,
) -> InlineKeyboardMarkup:
    def _check(v: bool) -> str:
        return "✅" if v else "❌"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🔴 Нагадування перед відкл. {_check(remind_off)}", callback_data="notif_toggle_remind_off")],
            [InlineKeyboardButton(text=f"🔴 Факт відключення {_check(fact_off)}", callback_data="notif_toggle_fact_off")],
            [InlineKeyboardButton(text=f"🟢 Нагадування перед вкл. {_check(remind_on)}", callback_data="notif_toggle_remind_on")],
            [InlineKeyboardButton(text=f"🟢 Факт включення {_check(fact_on)}", callback_data="notif_toggle_fact_on")],
            [
                InlineKeyboardButton(text=f"15 хв {_check(remind_15m)}", callback_data="notif_time_15"),
                InlineKeyboardButton(text=f"30 хв {_check(remind_30m)}", callback_data="notif_time_30"),
                InlineKeyboardButton(text=f"1 год {_check(remind_1h)}", callback_data="notif_time_60"),
            ],
            [InlineKeyboardButton(text="← Назад", callback_data="notif_main")],
        ]
    )


def get_notification_targets_keyboard(has_ip: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="📊 Зміни графіка →", callback_data="notif_target_type_schedule")],
        [InlineKeyboardButton(text="⏰ Нагадування →", callback_data="notif_target_type_remind")],
        [InlineKeyboardButton(text="⚡ Факт. стан (IP) →", callback_data="notif_target_type_power")],
    ]
    if not has_ip:
        rows.append([InlineKeyboardButton(text="📡 Налаштувати IP моніторинг", callback_data="settings_ip")])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="notif_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_notification_target_select_keyboard(
    target_type: str, current_target: str = "bot"
) -> InlineKeyboardMarkup:
    def _mark(t: str) -> str:
        return "● " if t == current_target else "○ "

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{_mark('bot')}📱 В бот", callback_data=f"notif_target_set_{target_type}_bot")],
            [InlineKeyboardButton(text=f"{_mark('channel')}📺 В канал", callback_data=f"notif_target_set_{target_type}_channel")],
            [InlineKeyboardButton(text=f"{_mark('both')}📱📺 Обидва", callback_data=f"notif_target_set_{target_type}_both")],
            [InlineKeyboardButton(text="← Назад", callback_data="notif_targets")],
        ]
    )


def get_notification_select_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Сповіщення в боті", callback_data="notif_select_bot")],
            [InlineKeyboardButton(text="Сповіщення для каналу", callback_data="notif_select_channel")],
            [InlineKeyboardButton(text="← Назад", callback_data="back_to_settings")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_channel_notification_keyboard(
    schedule: bool = True,
    remind_off: bool = True,
    fact_off: bool = True,
    remind_on: bool = True,
    fact_on: bool = True,
    remind_15m: bool = True,
    remind_30m: bool = False,
    remind_1h: bool = False,
) -> InlineKeyboardMarkup:
    def _check(v: bool) -> str:
        return "✅" if v else "❌"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Оновлення графіків {_check(schedule)}", callback_data="ch_notif_toggle_schedule")],
            [
                InlineKeyboardButton(text=f"1 год {_check(remind_1h)}", callback_data="ch_notif_time_60"),
                InlineKeyboardButton(text=f"30 хв {_check(remind_30m)}", callback_data="ch_notif_time_30"),
                InlineKeyboardButton(text=f"15 хв {_check(remind_15m)}", callback_data="ch_notif_time_15"),
            ],
            [InlineKeyboardButton(
                text=f"Фактично за IP-адресою {_check(fact_off)}",
                callback_data="ch_notif_toggle_fact",
            )],
            [InlineKeyboardButton(text="← Назад", callback_data="notif_main")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_ip_monitoring_keyboard(has_ip: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="ℹ️ Інструкція", callback_data="ip_instruction")],
    ]
    if not has_ip:
        rows.append([InlineKeyboardButton(text="✚ Підключити IP", callback_data="ip_setup")])
    else:
        rows.append([InlineKeyboardButton(text="📋 Показати поточний", callback_data="ip_show")])
        rows.append([InlineKeyboardButton(text="🗑️ Видалити IP", callback_data="ip_delete")])
    rows.extend([
        [InlineKeyboardButton(text="← Назад", callback_data="back_to_settings")],
        [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_ip_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✕ Скасувати", callback_data="ip_cancel")]]
    )


def get_cleanup_keyboard(
    auto_delete_commands: bool = False,
    auto_delete_bot_messages: bool = False,
) -> InlineKeyboardMarkup:
    cmd_icon = "✅" if auto_delete_commands else "⌨️"
    msg_icon = "✅" if auto_delete_bot_messages else "💬"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{cmd_icon} Видаляти команди", callback_data="cleanup_toggle_commands")],
            [InlineKeyboardButton(text=f"{msg_icon} Видаляти старі відповіді", callback_data="cleanup_toggle_messages")],
            [InlineKeyboardButton(text="← Назад", callback_data="back_to_settings")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_delete_data_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Скасувати", callback_data="back_to_settings"),
                InlineKeyboardButton(text="Продовжити", callback_data="delete_data_step2"),
            ],
        ]
    )


def get_delete_data_final_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Ні", callback_data="back_to_settings"),
                InlineKeyboardButton(text="Так, видалити", callback_data="confirm_delete_data"),
            ],
        ]
    )


def get_deactivate_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✓ Так, деактивувати", callback_data="confirm_deactivate"),
                InlineKeyboardButton(text="✕ Скасувати", callback_data="back_to_settings"),
            ],
        ]
    )


def get_format_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Графік відключень", callback_data="format_schedule_settings")],
            [InlineKeyboardButton(text="⚡ Фактичний стан", callback_data="format_power_settings")],
            [InlineKeyboardButton(text="← Назад", callback_data="settings_channel")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_format_schedule_keyboard(
    delete_old: bool = False,
    picture_only: bool = False,
) -> InlineKeyboardMarkup:
    del_icon = "✓" if delete_old else "○"
    pic_icon = "✓" if picture_only else "○"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Налаштувати текст графіка", callback_data="format_schedule_text")],
            [InlineKeyboardButton(text=f"{del_icon} Видаляти старий графік", callback_data="format_toggle_delete")],
            [InlineKeyboardButton(text=f"{pic_icon} Без тексту (тільки картинка)", callback_data="format_toggle_piconly")],
            [InlineKeyboardButton(text="← Назад", callback_data="format_menu")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_format_power_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text='🔴 Повідомлення "Світло зникло"', callback_data="format_power_off")],
            [InlineKeyboardButton(text='🟢 Повідомлення "Світло є"', callback_data="format_power_on")],
            [InlineKeyboardButton(text="🔄 Скинути все до стандартних", callback_data="format_reset_all_power")],
            [InlineKeyboardButton(text="← Назад", callback_data="format_menu")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_test_publication_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Графік відключень", callback_data="test_schedule")],
            [InlineKeyboardButton(text="⚡ Фактичний стан (світло є)", callback_data="test_power_on")],
            [InlineKeyboardButton(text="📴 Фактичний стан (світла немає)", callback_data="test_power_off")],
            [InlineKeyboardButton(text="✏️ Своє повідомлення", callback_data="test_custom")],
            [InlineKeyboardButton(text="← Назад", callback_data="settings_channel")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_error_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Спробувати ще", callback_data="back_to_main")],
        ]
    )


# ─── Admin keyboards ──────────────────────────────────────────────────────────


def get_admin_keyboard(open_tickets_count: int = 0) -> InlineKeyboardMarkup:
    tickets_text = f"📩 Звернення ({open_tickets_count})" if open_tickets_count else "📩 Звернення"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Аналітика", callback_data="admin_analytics"),
                InlineKeyboardButton(text="👥 Користувачі", callback_data="admin_users"),
            ],
            [InlineKeyboardButton(text=tickets_text, callback_data="admin_tickets")],
            [InlineKeyboardButton(text="📢 Розсилка", callback_data="admin_broadcast")],
            [InlineKeyboardButton(text="⚙️ Налаштування", callback_data="admin_settings_menu")],
            [
                InlineKeyboardButton(text="📡 Роутер", callback_data="admin_router"),
                InlineKeyboardButton(text="🔧 Тех. роботи", callback_data="admin_maintenance"),
            ],
            [InlineKeyboardButton(text="📞 Підтримка", callback_data="admin_support")],
            [InlineKeyboardButton(text="← Назад", callback_data="back_to_settings")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_admin_analytics_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Загальна статистика", callback_data="admin_stats")],
            [InlineKeyboardButton(text="📈 Ріст / Growth", callback_data="admin_growth")],
            [InlineKeyboardButton(text="← Назад", callback_data="admin_menu")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_admin_settings_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💻 Система", callback_data="admin_system")],
            [
                InlineKeyboardButton(text="⏱ Інтервали", callback_data="admin_intervals"),
                InlineKeyboardButton(text="⏸ Debounce", callback_data="admin_debounce"),
            ],
            [InlineKeyboardButton(text="⏸️ Режим паузи", callback_data="admin_pause")],
            [InlineKeyboardButton(text="🗑 Очистити базу", callback_data="admin_clear_db")],
            [InlineKeyboardButton(text="🔄 Перезапуск", callback_data="admin_restart")],
            [InlineKeyboardButton(text="← Назад", callback_data="admin_menu")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_maintenance_keyboard(enabled: bool = False) -> InlineKeyboardMarkup:
    toggle_text = "🟢 Вимкнути тех. роботи" if enabled else "🔴 Увімкнути тех. роботи"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle_text, callback_data="maintenance_toggle")],
            [InlineKeyboardButton(text="✏️ Змінити повідомлення", callback_data="maintenance_edit_message")],
            [InlineKeyboardButton(text="← Назад", callback_data="admin_menu")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_admin_intervals_keyboard(
    schedule_interval: int = 60, ip_interval: int = 2
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"⏱ Графіки: {schedule_interval // 60} хв", callback_data="admin_interval_schedule")],
            [InlineKeyboardButton(text=f"📡 IP: {ip_interval}", callback_data="admin_interval_ip")],
            [InlineKeyboardButton(text="← Назад", callback_data="admin_settings_menu")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_schedule_interval_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="1 хв", callback_data="admin_schedule_1"),
                InlineKeyboardButton(text="5 хв", callback_data="admin_schedule_5"),
            ],
            [
                InlineKeyboardButton(text="10 хв", callback_data="admin_schedule_10"),
                InlineKeyboardButton(text="15 хв", callback_data="admin_schedule_15"),
            ],
            [InlineKeyboardButton(text="← Назад", callback_data="admin_intervals")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_ip_interval_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="10 сек", callback_data="admin_ip_10"),
                InlineKeyboardButton(text="30 сек", callback_data="admin_ip_30"),
            ],
            [
                InlineKeyboardButton(text="1 хв", callback_data="admin_ip_60"),
                InlineKeyboardButton(text="2 хв", callback_data="admin_ip_120"),
            ],
            [InlineKeyboardButton(text="🔄 Динамічний", callback_data="admin_ip_0")],
            [InlineKeyboardButton(text="← Назад", callback_data="admin_intervals")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_debounce_keyboard(current_value: int = 0) -> InlineKeyboardMarkup:
    values = [0, 1, 2, 3, 5, 10, 15]
    rows: list[list[InlineKeyboardButton]] = []
    for v in values:
        if v == 0:
            mark = "✓ " if current_value == 0 else ""
            text = f"{mark}Вимкнено" if current_value == 0 else "❌ Вимкнути"
        else:
            mark = "✓ " if current_value == v else ""
            text = f"{mark}{v} хв"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"debounce_set_{v}")])
    rows.extend([
        [InlineKeyboardButton(text="← Назад", callback_data="admin_menu")],
        [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_pause_menu_keyboard(is_paused: bool = False) -> InlineKeyboardMarkup:
    status_text = "🔴 Бот на паузі" if is_paused else "🟢 Бот активний"
    toggle_text = "🟢 Вимкнути паузу" if is_paused else "🔴 Увімкнути паузу"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=status_text, callback_data="pause_status")],
            [InlineKeyboardButton(text=toggle_text, callback_data="pause_toggle")],
            [InlineKeyboardButton(text="📋 Налаштувати повідомлення", callback_data="pause_message_settings")],
            [InlineKeyboardButton(text="🏷 Тип паузи", callback_data="pause_type_select")],
            [InlineKeyboardButton(text="📜 Лог паузи", callback_data="pause_log")],
            [InlineKeyboardButton(text="← Назад", callback_data="admin_settings_menu")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_pause_type_keyboard(current_type: str = "update") -> InlineKeyboardMarkup:
    types = [
        ("🔧 Оновлення", "update"),
        ("🚨 Аварія", "emergency"),
        ("🔨 Обслуговування", "maintenance"),
        ("🧪 Тестування", "testing"),
    ]
    rows = []
    for text, t in types:
        mark = "● " if t == current_type else "○ "
        rows.append([InlineKeyboardButton(text=f"{mark}{text}", callback_data=f"pause_type_{t}")])
    rows.extend([
        [InlineKeyboardButton(text="← Назад", callback_data="admin_pause")],
        [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_pause_message_keyboard(show_support_button: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="🔧 Бот тимчасово недоступний...", callback_data="pause_template_1")],
        [InlineKeyboardButton(text="⏸️ Бот на паузі. Скоро повернемось", callback_data="pause_template_2")],
        [InlineKeyboardButton(text="🔧 Бот тимчасово оновлюється. Спробуйте пізніше.", callback_data="pause_template_3")],
        [InlineKeyboardButton(text="⏸️ Бот на паузі. Скоро повернемось.", callback_data="pause_template_4")],
        [InlineKeyboardButton(text="🚧 Технічні роботи. Дякуємо за розуміння.", callback_data="pause_template_5")],
        [InlineKeyboardButton(text="✏️ Свій текст...", callback_data="pause_custom_message")],
    ]
    support_mark = "✓" if show_support_button else "○"
    rows.append(
        [InlineKeyboardButton(
            text=f'{support_mark} Показувати кнопку "Обговорення/Підтримка"',
            callback_data="pause_toggle_support",
        )]
    )
    rows.extend([
        [InlineKeyboardButton(text="← Назад", callback_data="admin_pause")],
        [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_growth_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Метрики", callback_data="growth_metrics")],
            [InlineKeyboardButton(text="🎯 Етап росту", callback_data="growth_stage")],
            [InlineKeyboardButton(text="🔐 Реєстрація", callback_data="growth_registration")],
            [InlineKeyboardButton(text="📝 Події", callback_data="growth_events")],
            [InlineKeyboardButton(text="← Назад", callback_data="admin_analytics")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_growth_stage_keyboard(current_stage: int = 0) -> InlineKeyboardMarkup:
    stages = [
        ("Етап 0: Закрите тестування (0-50)", 0),
        ("Етап 1: Відкритий тест (50-300)", 1),
        ("Етап 2: Контрольований ріст (300-1000)", 2),
        ("Етап 3: Активний ріст (1000-5000)", 3),
        ("Етап 4: Масштаб (5000+)", 4),
    ]
    rows = []
    for text, s in stages:
        mark = "● " if s == current_stage else "○ "
        rows.append([InlineKeyboardButton(text=f"{mark}{text}", callback_data=f"growth_stage_{s}")])
    rows.extend([
        [InlineKeyboardButton(text="← Назад", callback_data="admin_growth")],
        [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_growth_registration_keyboard(enabled: bool = True) -> InlineKeyboardMarkup:
    status_text = "🟢 Реєстрація увімкнена" if enabled else "🔴 Реєстрація вимкнена"
    toggle_text = "🔴 Вимкнути реєстрацію" if enabled else "🟢 Увімкнути реєстрацію"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=status_text, callback_data="growth_reg_status")],
            [InlineKeyboardButton(text=toggle_text, callback_data="growth_reg_toggle")],
            [InlineKeyboardButton(text="← Назад", callback_data="admin_growth")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_restart_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Так, перезапустити", callback_data="admin_restart_confirm"),
                InlineKeyboardButton(text="❌ Скасувати", callback_data="admin_settings_menu"),
            ],
        ]
    )


def get_users_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статистика користувачів", callback_data="admin_users_stats")],
            [InlineKeyboardButton(text="📋 Список користувачів", callback_data="admin_users_list_1")],
            [InlineKeyboardButton(text="← Назад", callback_data="admin_menu")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_admin_ticket_keyboard(ticket_id: int, status: str = "open") -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="💬 Відповісти", callback_data=f"admin_ticket_reply_{ticket_id}")],
    ]
    if status == "open":
        rows.append([InlineKeyboardButton(text="✅ Закрити", callback_data=f"admin_ticket_close_{ticket_id}")])
    else:
        rows.append(
            [InlineKeyboardButton(text="🔄 Відкрити знову", callback_data=f"admin_ticket_reopen_{ticket_id}")]
        )
    rows.append([InlineKeyboardButton(text="← Назад до списку", callback_data="admin_tickets")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_admin_tickets_list_keyboard(
    tickets: list, page: int = 1, per_page: int = 10
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    start = (page - 1) * per_page
    page_tickets = tickets[start : start + per_page]

    for t in page_tickets:
        status_icon = "🟢" if t.status == "open" else "🔴"
        type_icon = {"bug": "🐛", "idea": "💡", "other": "💬", "region_request": "🏙"}.get(t.type, "📩")
        text = f"{status_icon}{type_icon} #{t.id}"
        if t.subject:
            text += f" - {t.subject[:30]}"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"admin_ticket_view_{t.id}")])

    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="← Попередня", callback_data=f"admin_tickets_page_{page - 1}"))
    total_pages = max(1, (len(tickets) + per_page - 1) // per_page)
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Наступна →", callback_data=f"admin_tickets_page_{page + 1}"))
    if nav_row:
        rows.append(nav_row)

    rows.extend([
        [InlineKeyboardButton(text="← Назад", callback_data="admin_menu")],
        [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_admin_router_keyboard(has_ip: bool = False, notifications_on: bool = True) -> InlineKeyboardMarkup:
    ip_text = "✏️ Змінити IP" if has_ip else "✏️ Налаштувати IP"
    notif_text = "✓ Сповіщення" if notifications_on else "✗ Сповіщення"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=ip_text, callback_data="admin_router_set_ip")],
            [InlineKeyboardButton(text=notif_text, callback_data="admin_router_toggle_notify")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_router_stats")],
            [InlineKeyboardButton(text="🔄 Оновити", callback_data="admin_router_refresh")],
            [InlineKeyboardButton(text="← Назад", callback_data="admin_menu")],
            [InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")],
        ]
    )


def get_admin_support_keyboard(
    current_mode: str = "bot", support_url: str | None = None
) -> InlineKeyboardMarkup:
    channel_mark = "●" if current_mode == "channel" else "○"
    bot_mark = "●" if current_mode == "bot" else "○"
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=f"{channel_mark} Через канал (листування)", callback_data="admin_support_channel")],
        [InlineKeyboardButton(text=f"{bot_mark} Через бот (тікети)", callback_data="admin_support_bot")],
    ]
    if current_mode == "channel":
        url_text = "✏️ Змінити посилання" if support_url else "✏️ Додати посилання"
        rows.append([InlineKeyboardButton(text=url_text, callback_data="admin_support_edit_url")])
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="admin_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_feedback_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🐛 Баг", callback_data="feedback_type_bug")],
            [InlineKeyboardButton(text="💡 Ідея", callback_data="feedback_type_idea")],
            [InlineKeyboardButton(text="💬 Інше", callback_data="feedback_type_other")],
            [InlineKeyboardButton(text="← Назад", callback_data="back_to_main")],
        ]
    )


def get_feedback_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Надіслати", callback_data="feedback_confirm"),
                InlineKeyboardButton(text="❌ Скасувати", callback_data="feedback_cancel"),
            ],
        ]
    )


def get_region_request_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Надіслати", callback_data="region_request_confirm"),
                InlineKeyboardButton(text="❌ Скасувати", callback_data="region_request_cancel"),
            ],
        ]
    )


def get_broadcast_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Скасувати", callback_data="broadcast_cancel")]]
    )
