from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.constants.regions import KYIV_QUEUES, REGION_QUEUES, STANDARD_QUEUES

# ─── Custom animated emoji IDs (from old bot, 1:1) ────────────────────────

E_SCHEDULE = "5210956306952758910"
E_HELP = "5443038326535759644"
E_STATS = "5190806721286657692"
E_TIMER = "5382194935057372936"
E_SETTINGS = "5341715473882955310"
E_RESUME = "5348125953090403204"
E_PAUSE_CHANNEL = "5359543311897998264"
E_REGION = "5399898266265475100"
E_REFRESH = "5017470156276761427"
E_IP = "5447410659077661506"
E_CHANNEL = "5424818078833715060"
E_ALERTS = "5458603043203327669"
E_ADMIN = "5217822164362739968"
E_DELETE_DATA = "5445267414562389170"
E_SCHEDULE_CHANGES = "5231200819986047254"
E_BOT_NOTIF = "5372981976804366741"
E_FACT = "5382194935057372936"
E_CONFIRM_CHANGE = "5206607081334906820"
E_CANCEL = "5210952531676504517"
E_WELCOME = "5472055112702629499"
E_CHECK = "5870509845911702494"
E_WARN = "5447644880824181073"
E_QUEUE = "5390854796011906616"
E_BELL = "5262598817626234330"
E_HOURGLASS = "5451732530048802485"

E_BACK = None
E_MENU = None
E_IP_SETTINGS = "5312532335042794821"
E_IP_ADDR = "5312283536177273995"
E_ONLINE = "5309771882252243514"
E_OFFLINE = "5312380297495484470"
E_CHANGE_IP = "5312336892555990307"
E_DELETE_IP = "5312141591803109522"
E_PING_CHECK = "5312535839736111416"
E_PING_LOADING = "5890925363067886150"
E_SUCCESS = "5264973221576349285"
E_ERROR_PING = "5312438206539536342"
E_PING_FAIL = "5264933407229517572"
E_SUPPORT = "5310296757320586255"
E_REPLY = "5312237842020209022"

E_INSTRUCTION = "5319069545850247853"
E_INSTR_HELP = "5321151063095546482"
E_FAQ = "5319180751143476261"
E_NOTIF_SECTION = "5262598817626234330"
E_CHANNEL_SECTION = "5312374181462055424"
E_IP_SECTION = "5312283536177273995"
E_SCHEDULE_SEC = "5264999721524562037"
E_BOT_SETTINGS = "5312280340721604022"
E_NEWS = "5312374181462055424"
E_DISCUSS = "5312237842020209022"


def _btn(
    text: str,
    callback_data: str,
    emoji_id: str | None = None,
    style: str | None = None,
    **kwargs,
) -> InlineKeyboardButton:
    params: dict = {"text": text, "callback_data": callback_data, **kwargs}
    if emoji_id:
        params["icon_custom_emoji_id"] = emoji_id
    if style:
        params["style"] = style
    return InlineKeyboardButton(**params)


def _url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def _url_btn_with_emoji(text: str, url: str, emoji_id: str | None = None) -> InlineKeyboardButton:
    params: dict = {"text": text, "url": url}
    if emoji_id:
        params["icon_custom_emoji_id"] = emoji_id
    return InlineKeyboardButton(**params)



# ─── Main menu ─────────────────────────────────────────────────────────────


def get_main_menu(channel_paused: bool = False, has_channel: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            _btn("Графік", "menu_schedule", E_SCHEDULE_SEC),
            _btn("Допомога", "menu_help", E_HELP),
        ],
        [
            _btn("Сповіщення", "settings_alerts", E_ALERTS),
            _btn("Канал", "settings_channel", E_CHANNEL),
        ],
        [_btn("Налаштування", "menu_settings", E_BOT_SETTINGS)],
    ]
    if has_channel:
        if channel_paused:
            rows.append([_btn("Відновити роботу каналу", "channel_resume", E_RESUME)])
        else:
            rows.append([_btn("Тимчасово зупинити канал", "channel_pause", E_PAUSE_CHANNEL)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_reminder_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        _btn("Графік", "reminder_show_schedule", E_SCHEDULE_SEC),
        _btn("Зрозуміло", "reminder_dismiss", E_SUCCESS),
    ]])


def get_understood_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        _btn("Зрозуміло", "reminder_dismiss", E_SUCCESS),
    ]])


def get_schedule_view_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("Замінити", "my_queues", E_REGION),
            _btn("Перевірити", "schedule_check", E_REFRESH),
        ],
        [_btn("⤴ Меню", "back_to_main")],
    ])


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


def get_settings_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            _btn("Регіон", "settings_region", E_INSTRUCTION),
            _btn("IP", "settings_ip", E_IP_SECTION),
        ],
        [
            _btn("Канал", "settings_channel", E_CHANNEL_SECTION),
            _btn("Сповіщення", "settings_alerts", E_NOTIF_SECTION),
        ],
        [_btn("🚨 Аварійні вимк.", "settings_emergency")],
        [_btn("🗑 Очищення", "settings_cleanup")],
    ]
    if is_admin:
        rows.append([_btn("Адмін-панель", "settings_admin", E_ADMIN)])
    rows.append([_btn("Видалити мої дані", "settings_delete_data", E_DELETE_DATA)])
    rows.append([_btn("⤴ Меню", "back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_statistics_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("⚡ Відключення за тиждень", "stats_week")],
        [_btn("📡 Статус пристрою", "stats_device")],
        [_btn("⚙️ Мої налаштування", "stats_settings")],
        [_btn("⤴ Меню", "back_to_main")],
    ])


def get_help_keyboard(faq_url: str | None = None, support_url: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [_btn("Інструкція", "help_instructions", E_INSTR_HELP)],
    ]
    row2: list[InlineKeyboardButton] = []
    if faq_url:
        row2.append(_btn("FAQ", "help_faq", E_FAQ, style="primary"))
    if support_url:
        row2.append(_btn("Підтримка", "help_support", E_SUPPORT, style="primary"))
    if row2:
        rows.append(row2)
    rows.append([
        _url_btn_with_emoji("Новини ↗", "https://t.me/Voltyk_news", E_NEWS),
        _url_btn_with_emoji("Обговорення ↗", "https://t.me/voltyk_chat", E_DISCUSS),
    ])
    rows.append([_btn("⤴ Меню", "back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_faq_keyboard(faq_url: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if faq_url:
        rows.append([_url_btn_with_emoji("Перейти в FAQ ↗", faq_url, E_FAQ)])
    rows.append([_btn("← Назад", "menu_help"), _btn("⤴ Меню", "back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_support_keyboard(support_url: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if support_url:
        rows.append([_url_btn_with_emoji("Написати адміністратору ↗", support_url, E_SUPPORT)])
    rows.append([_btn("← Назад", "menu_help"), _btn("⤴ Меню", "back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_instructions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("Регіон і черга", "instr_region", E_INSTRUCTION),
            _btn("Сповіщення", "instr_notif", E_NOTIF_SECTION),
        ],
        [
            _btn("Канал", "instr_channel", E_CHANNEL_SECTION),
            _btn("IP моніторинг", "instr_ip", E_IP_SECTION),
        ],
        [
            _btn("Графік відключень", "instr_schedule", E_SCHEDULE_SEC),
            _btn("Налаштування бота", "instr_bot_settings", E_BOT_SETTINGS),
        ],
        [_btn("← Назад", "menu_help"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_instruction_section_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("← Назад", "help_instructions"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_restoration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🔄 Відновити налаштування", "restore_profile")],
        [_btn("🆕 Почати заново", "create_new_profile")],
    ])


def get_wizard_notify_target_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📱 У цьому боті", "wizard_notify_bot")],
        [_btn("📺 У Telegram-каналі", "wizard_notify_channel")],
    ])


# ─── Notification keyboards (wizard + settings) ───────────────────────────


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


def get_wizard_bot_notification_keyboard(**kw) -> InlineKeyboardMarkup:
    return _notif_keyboard("wizard_notif", kw.get("schedule_changes", True), kw.get("fact_off", True),
                           kw.get("remind_15m", True), kw.get("remind_30m", False), kw.get("remind_1h", False),
                           "wizard_notify_back", "wizard_bot_done")


def get_wizard_channel_notification_keyboard(**kw) -> InlineKeyboardMarkup:
    return _notif_keyboard("wizard_ch_notif", kw.get("schedule_changes", True), kw.get("fact_off", True),
                           kw.get("remind_15m", True), kw.get("remind_30m", False), kw.get("remind_1h", False),
                           "wizard_channel_back", "wizard_channel_done")


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


# ─── Channel keyboards ────────────────────────────────────────────────────


def get_channel_pending_confirm_keyboard(channel_id: str) -> InlineKeyboardMarkup:
    """Для підтвердження каналу зі сторінки підключення (channel_confirm_)."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        _btn("Так, підключити", f"channel_confirm_{channel_id}", style="success"),
        _btn("Ні", "settings_channel", style="danger"),
    ]])


def get_channel_connect_confirm_keyboard(channel_id: str) -> InlineKeyboardMarkup:
    """Для підтвердження нового каналу (connect_channel_)."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        _btn("Так, підключити", f"connect_channel_{channel_id}", style="success"),
        _btn("Ні", "cancel_channel_connect", style="danger"),
    ]])


def get_channel_replace_confirm_keyboard(channel_id: str) -> InlineKeyboardMarkup:
    """Для підтвердження заміни каналу (replace_channel_)."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        _btn("Так, замінити", f"replace_channel_{channel_id}", style="success"),
        _btn("Залишити", "keep_current_channel", style="danger"),
    ]])


def get_channel_menu_keyboard(
    channel_id: str | None = None, is_public: bool = False,
    channel_username: str | None = None, channel_status: str = "active",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if not channel_id:
        rows.append([_btn("✚ Підключити канал", "channel_connect")])
    else:
        if is_public and channel_username:
            rows.append([_url_btn("📺 Відкрити канал", f"https://t.me/{channel_username}")])
        rows.append([_btn("ℹ️ Інфо", "channel_info"), _btn("✏️ Назва", "channel_edit_title")])
        rows.append([_btn("📝 Опис", "channel_edit_description"), _btn("📋 Формат", "channel_format")])
        rows.append([
            _btn("🧪 Тест", "channel_test"),
            _btn("⚙️ Перепідключити", "channel_reconnect") if channel_status == "blocked"
            else _btn("🔴 Вимкнути", "channel_disable"),
        ])
        rows.append([_btn("🔔 Сповіщення", "channel_notifications")])
    rows.append([_btn("← Назад", "back_to_settings"), _btn("⤴ Меню", "back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── IP keyboards ─────────────────────────────────────────────────────────


def get_ip_monitoring_keyboard_no_ip() -> InlineKeyboardMarkup:
    """Екран 1А — IP не підключено: кнопка Скасувати (червона)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("Скасувати", "ip_cancel_to_settings", style="danger")],
    ])


def get_ip_management_keyboard() -> InlineKeyboardMarkup:
    """Екран 1Б — IP підключено: кнопки керування."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("Змінити IP", "ip_change", E_CHANGE_IP),
            _btn("Видалити IP", "ip_delete_confirm", E_DELETE_IP),
        ],
        [_btn("Перевірити пінг", "ip_ping_check", E_PING_CHECK)],
        [
            _btn("← Назад", "back_to_settings"),
            _btn("⤴ Меню", "back_to_main"),
        ],
    ])


def get_ip_change_confirm_keyboard() -> InlineKeyboardMarkup:
    """Екран 2 — Підтвердження зміни IP."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("Так", "ip_change_confirm", style="primary"),
            _btn("Скасувати", "ip_cancel_to_management", style="danger"),
        ],
    ])


def get_ip_delete_confirm_keyboard() -> InlineKeyboardMarkup:
    """Екран 3 — Підтвердження видалення IP."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("Видалити", "ip_delete_execute", style="danger"),
            _btn("Скасувати", "ip_cancel_to_management", style="primary"),
        ],
    ])


def get_ip_deleted_keyboard() -> InlineKeyboardMarkup:
    """Екран 4 — Після видалення IP."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("← Назад", "back_to_settings"),
            _btn("⤴ Меню", "back_to_main"),
        ],
    ])


def get_ip_saved_keyboard() -> InlineKeyboardMarkup:
    """Екран 5 — Після збереження IP (legacy, backward compatibility)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("← Назад", "back_to_settings"),
            _btn("⤴ Меню", "back_to_main"),
        ],
    ])


def get_ip_saved_success_keyboard() -> InlineKeyboardMarkup:
    """Екран 5 — Після збереження IP, пінг успішний."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("← Назад", "settings_ip"),
            _btn("⤴ Меню", "back_to_main"),
        ],
    ])


def get_ip_saved_fail_keyboard(support_url: str | None = None) -> InlineKeyboardMarkup:
    """Екран 5 — Після збереження IP, пінг не пройшов."""
    rows: list[list[InlineKeyboardButton]] = []
    if support_url:
        rows.append([_url_btn_with_emoji("Підтримка", support_url, E_SUPPORT)])
    rows.append([
        _btn("← Назад", "settings_ip"),
        _btn("⤴ Меню", "back_to_main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_ip_ping_result_keyboard() -> InlineKeyboardMarkup:
    """Екран 6 — Після перевірки пінгу (успіх)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("← Назад", "settings_ip"),
            _btn("⤴ Меню", "back_to_main"),
        ],
    ])


def get_ip_ping_fail_keyboard(support_url: str | None = None) -> InlineKeyboardMarkup:
    """Екран 6 — Після перевірки пінгу (невдача)."""
    rows: list[list[InlineKeyboardButton]] = []
    if support_url:
        rows.append([_url_btn_with_emoji("Підтримка", support_url, E_SUPPORT)])
    rows.append([
        _btn("← Назад", "settings_ip"),
        _btn("⤴ Меню", "back_to_main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_ip_ping_error_keyboard(support_url: str | None = None) -> InlineKeyboardMarkup:
    """Щоденне повідомлення про помилку пінгу — кнопка Підтримка."""
    rows: list[list[InlineKeyboardButton]] = []
    if support_url:
        rows.append([_url_btn_with_emoji("Підтримка", support_url, E_SUPPORT)])
    return InlineKeyboardMarkup(inline_keyboard=rows)




# ─── Cleanup / Data deletion ──────────────────────────────────────────────


def get_cleanup_keyboard(auto_delete_commands: bool = False, auto_delete_bot_messages: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("⌨️ Видаляти команди", "cleanup_toggle_commands", style="success" if auto_delete_commands else None)],
        [_btn("💬 Видаляти старі відповіді", "cleanup_toggle_messages", style="success" if auto_delete_bot_messages else None)],
        [_btn("← Назад", "back_to_settings"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_delete_data_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("Скасувати", "back_to_settings"), _btn("Продовжити", "delete_data_step2")],
    ])


def get_delete_data_final_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("Ні", "back_to_settings"), _btn("Так, видалити", "confirm_delete_data", E_DELETE_DATA)],
    ])


def get_deactivate_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✓ Так, деактивувати", "confirm_deactivate")],
        [_btn("✕ Скасувати", "back_to_settings")],
    ])


# ─── Format keyboards ─────────────────────────────────────────────────────


def get_format_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📊 Графік відключень", "format_schedule_settings")],
        [_btn("⚡ Фактичний стан", "format_power_settings")],
        [_btn("← Назад", "settings_channel"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_format_schedule_keyboard(delete_old: bool = False, picture_only: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📝 Налаштувати текст графіка", "format_schedule_text")],
        [_btn("Видаляти старий графік", "format_toggle_delete", style="success" if delete_old else None)],
        [_btn("Без тексту (тільки картинка)", "format_toggle_piconly", style="success" if picture_only else None)],
        [_btn("← Назад", "format_menu"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_format_power_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn('🔴 Повідомлення "Світло зникло"', "format_power_off")],
        [_btn('🟢 Повідомлення "Світло є"', "format_power_on")],
        [_btn("🔄 Скинути все до стандартних", "format_reset_all_power")],
        [_btn("← Назад", "format_menu"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_test_publication_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📊 Графік відключень", "test_schedule")],
        [_btn("⚡ Фактичний стан (світло є)", "test_power_on")],
        [_btn("📴 Фактичний стан (світла немає)", "test_power_off")],
        [_btn("✏️ Своє повідомлення", "test_custom")],
        [_btn("← Назад", "settings_channel"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_error_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🔄 Спробувати ще", "back_to_main")],
    ])


def get_broadcast_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("❌ Скасувати", "broadcast_cancel")]])


# ─── Admin keyboards ──────────────────────────────────────────────────────


def get_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📊 Аналітика", "admin_analytics"), _btn("👥 Користувачі", "admin_users")],
        [_btn("📢 Розсилка", "admin_broadcast")],
        [_btn("⚙️ Налаштування", "admin_settings_menu"), _btn("📡 Роутер", "admin_router")],
        [_btn("🔧 Тех. роботи", "admin_maintenance")],
        [_btn("← Назад", "back_to_settings"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_admin_analytics_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📊 Загальна статистика", "admin_stats")],
        [_btn("📈 Ріст / Growth", "admin_growth")],
        [_btn("← Назад", "admin_menu"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_admin_settings_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("💻 Система", "admin_system"), _btn("⏱ Інтервали", "admin_intervals")],
        [_btn("⏸ Debounce", "admin_debounce"), _btn("⏸️ Режим паузи", "admin_pause")],
        [_btn("🔄 Cooldown перевірки", "admin_refresh_cooldown")],
        [_btn("🗑 Очистити базу", "admin_clear_db"), _btn("🔄 Перезапуск", "admin_restart")],
        [_btn("← Назад", "admin_menu"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_refresh_cooldown_keyboard(current_seconds: int = 30) -> InlineKeyboardMarkup:
    options = [(5, "5 сек"), (10, "10 сек"), (20, "20 сек"), (30, "30 сек"), (60, "60 сек")]
    rows = []
    for secs, label in options:
        selected = current_seconds == secs
        rows.append([_btn(label, f"admin_cooldown_set_{secs}", style="success" if selected else None)])
    rows.append([_btn("← Назад", "admin_settings_menu"), _btn("⤴ Меню", "back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_maintenance_keyboard(enabled: bool = False) -> InlineKeyboardMarkup:
    t = "🟢 Вимкнути тех. роботи" if enabled else "🔴 Увімкнути тех. роботи"
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(t, "maintenance_toggle")],
        [_btn("✏️ Змінити повідомлення", "maintenance_edit_message")],
        [_btn("← Назад", "admin_menu"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_admin_intervals_keyboard(schedule_interval: int = 60, ip_interval: int = 2) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(f"⏱ Графіки: {schedule_interval // 60} хв", "admin_interval_schedule")],
        [_btn(f"📡 IP: {ip_interval}", "admin_interval_ip")],
        [_btn("← Назад", "admin_settings_menu"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_schedule_interval_keyboard(current_seconds: int = 0) -> InlineKeyboardMarkup:
    def _s(minutes: int) -> InlineKeyboardButton:
        selected = current_seconds == minutes * 60
        return _btn(f"{minutes} хв", f"admin_schedule_{minutes}", style="success" if selected else None)

    return InlineKeyboardMarkup(inline_keyboard=[
        [_s(3), _s(5), _s(10), _s(15)],
        [_btn("← Назад", "admin_intervals"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_ip_interval_keyboard(current_seconds: int = 10) -> InlineKeyboardMarkup:
    def _i(seconds: int, label: str) -> InlineKeyboardButton:
        selected = current_seconds == seconds
        return _btn(label, f"admin_ip_{seconds}", style="success" if selected else None)

    return InlineKeyboardMarkup(inline_keyboard=[
        [_i(10, "10 сек"), _i(30, "30 сек"), _i(60, "1 хв"), _i(120, "2 хв")],
        [_i(0, "🔄 Динамічний")],
        [_btn("← Назад", "admin_intervals"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_debounce_keyboard(current_value: int = 0) -> InlineKeyboardMarkup:
    def _d(v: int, label: str) -> InlineKeyboardButton:
        selected = current_value == v
        return _btn(label, f"debounce_set_{v}", style="success" if selected else None)

    return InlineKeyboardMarkup(inline_keyboard=[
        [_d(0, "❌ Вимкнути")],
        [_d(1, "1 хв"), _d(2, "2 хв"), _d(3, "3 хв")],
        [_d(5, "5 хв"), _d(10, "10 хв"), _d(15, "15 хв")],
        [_btn("← Назад", "admin_menu"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_pause_menu_keyboard(is_paused: bool = False) -> InlineKeyboardMarkup:
    status = "🔴 Бот на паузі" if is_paused else "🟢 Бот активний"
    toggle = "🟢 Вимкнути паузу" if is_paused else "🔴 Увімкнути паузу"
    rows = [
        [_btn(status, "pause_status")],
        [_btn(toggle, "pause_toggle")],
        [_btn("📋 Налаштувати повідомлення", "pause_message_settings")],
    ]
    if is_paused:
        rows.append([_btn("🏷 Тип паузи", "pause_type_select")])
    rows.append([_btn("📜 Лог паузи", "pause_log")])
    rows.append([_btn("← Назад", "admin_settings_menu"), _btn("⤴ Меню", "back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_pause_type_keyboard(current_type: str = "update") -> InlineKeyboardMarkup:
    types = [("🔧 Оновлення", "update"), ("🚨 Аварія", "emergency"),
             ("🔨 Обслуговування", "maintenance"), ("🧪 Тестування", "testing")]
    rows = []
    for text, t in types:
        selected = t == current_type
        rows.append([_btn(text, f"pause_type_{t}", style="success" if selected else None)])
    rows.append([_btn("← Назад", "admin_pause"), _btn("⤴ Меню", "back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_pause_message_keyboard(show_support_button: bool = False, current_message: str = "") -> InlineKeyboardMarkup:
    templates = [
        ("🔧 Бот тимчасово недоступний. Спробуйте пізніше.", "pause_template_1"),
        ("⏸️ Бот на паузі. Скоро повернемось", "pause_template_2"),
        ("🔧 Бот тимчасово оновлюється. Спробуйте пізніше.", "pause_template_3"),
        ("⏸️ Бот на паузі. Скоро повернемось.", "pause_template_4"),
        ("🚧 Технічні роботи. Дякуємо за розуміння.", "pause_template_5"),
    ]
    template_texts = {t for t, _ in templates}
    rows = []
    for text, cb in templates:
        selected = text == current_message
        rows.append([_btn(text, cb, style="success" if selected else None)])
    is_custom = bool(current_message) and current_message not in template_texts
    rows.append([_btn("✏️ Свій текст...", "pause_custom_message", style="success" if is_custom else None)])
    support_style = "success" if show_support_button else None
    rows.append([_btn('Показувати кнопку "Обговорення/Підтримка"', "pause_toggle_support", style=support_style)])
    rows.append([_btn("← Назад", "admin_pause"), _btn("⤴ Меню", "back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_growth_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📊 Метрики", "growth_metrics")],
        [_btn("🎯 Етап росту", "growth_stage")],
        [_btn("🔐 Реєстрація", "growth_registration")],
        [_btn("📝 Події", "growth_events")],
        [_btn("← Назад", "admin_analytics"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_growth_stage_keyboard(current_stage: int = 0) -> InlineKeyboardMarkup:
    stages = [("Етап 0: Закрите тестування (0-50)", 0), ("Етап 1: Відкритий тест (50-300)", 1),
              ("Етап 2: Контрольований ріст (300-1000)", 2), ("Етап 3: Активний ріст (1000-5000)", 3),
              ("Етап 4: Масштаб (5000+)", 4)]
    rows = []
    for text, s in stages:
        selected = s == current_stage
        rows.append([_btn(text, f"growth_stage_{s}", style="success" if selected else None)])
    rows.append([_btn("← Назад", "admin_growth"), _btn("⤴ Меню", "back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_growth_registration_keyboard(enabled: bool = True) -> InlineKeyboardMarkup:
    st = "🟢 Реєстрація увімкнена" if enabled else "🔴 Реєстрація вимкнена"
    tg = "🔴 Вимкнути реєстрацію" if enabled else "🟢 Увімкнути реєстрацію"
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(st, "growth_reg_status")],
        [_btn(tg, "growth_reg_toggle")],
        [_btn("← Назад", "admin_growth"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_restart_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✅ Так, перезапустити", "admin_restart_confirm")],
        [_btn("❌ Скасувати", "admin_settings_menu")],
    ])


def get_users_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("📊 Статистика користувачів", "admin_users_stats")],
        [_btn("📋 Список користувачів", "admin_users_list_1")],
        [_btn("← Назад", "admin_menu"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_admin_router_keyboard(has_ip: bool = False, notifications_on: bool = True) -> InlineKeyboardMarkup:
    if not has_ip:
        return InlineKeyboardMarkup(inline_keyboard=[
            [_btn("✏️ Налаштувати IP", "admin_router_set_ip")],
            [_btn("← Назад", "admin_menu"), _btn("⤴ Меню", "back_to_main")],
        ])
    n = "✓ Сповіщення" if notifications_on else "✗ Сповіщення"
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✏️ Змінити IP", "admin_router_set_ip"), _btn(n, "admin_router_toggle_notify")],
        [_btn("📊 Статистика", "admin_router_stats"), _btn("🔄 Оновити", "admin_router_refresh")],
        [_btn("← Назад", "admin_menu"), _btn("⤴ Меню", "back_to_main")],
    ])


# ─── Emergency outage keyboards ────────────────────────────────────────────


def get_emergency_no_address_keyboard() -> InlineKeyboardMarkup:
    """Screen: emergency address not configured."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🏠 Налаштувати адресу", "emergency_setup")],
        [_btn("← Назад", "back_to_settings")],
    ])


def get_emergency_management_keyboard() -> InlineKeyboardMarkup:
    """Screen: emergency address configured — management options."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🔍 Перевірити зараз", "emergency_check_now")],
        [
            _btn("✏️ Змінити", "emergency_change"),
            _btn("🗑 Видалити", "emergency_delete_confirm"),
        ],
        [_btn("← Назад", "back_to_settings")],
    ])


def get_emergency_change_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✅ Так", "emergency_change_confirm")],
        [_btn("Скасувати", "emergency_cancel_to_management")],
    ])


def get_emergency_delete_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🗑 Так, видалити", "emergency_delete_execute")],
        [_btn("Скасувати", "emergency_cancel_to_management")],
    ])


def get_emergency_saved_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            _btn("← Назад", "settings_emergency"),
            _btn("⤴ Меню", "back_to_main"),
        ],
    ])


def get_emergency_cancel_keyboard() -> InlineKeyboardMarkup:
    """Cancel button shown during multi-step address input."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("Скасувати", "emergency_cancel_to_settings")],
    ])
