from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.common import _btn


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
        [_btn("🖼 Режим графіка", "admin_chart_render")],
        [_btn("😀 Емодзі кнопок", "admin_button_emoji")],
        [_btn("🗑 Очистити базу", "admin_clear_db"), _btn("🔄 Перезапуск", "admin_restart")],
        [_btn("← Назад", "admin_menu"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_button_emoji_mode_keyboard(custom_enabled: bool = True) -> InlineKeyboardMarkup:
    custom_style = "success" if custom_enabled else None
    regular_style = "success" if not custom_enabled else None
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("✨ Кастомні (Premium)", "admin_button_emoji_set_custom", style=custom_style)],
        [_btn("🙂 Звичайні", "admin_button_emoji_set_regular", style=regular_style)],
        [_btn("← Назад", "admin_settings_menu"), _btn("⤴ Меню", "back_to_main")],
    ])


def get_chart_render_mode_keyboard(current_mode: str = "on_change") -> InlineKeyboardMarkup:
    def _mode_btn(label: str, mode: str) -> InlineKeyboardButton:
        selected = mode == current_mode
        prefix = "✅ " if selected else ""
        return _btn(f"{prefix}{label}", f"chart_render_mode_{mode}",
                    style="success" if selected else None)

    return InlineKeyboardMarkup(inline_keyboard=[
        [_mode_btn("При зміні розкладу", "on_change")],
        [_mode_btn("При кожному запиті", "on_demand")],
        [_btn("👁 Перегляд графіка", "chart_preview_menu")],
        [_btn("← Назад", "admin_settings_menu")],
    ])


def get_chart_preview_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("💡 2 відключення на день",  "chart_preview:two_outages")],
        [_btn("⚡ 3 відключення на день",  "chart_preview:three_outages")],
        [_btn("🚫 Цілий день без світла",  "chart_preview:allday")],
        [_btn("⏱ 30-хвилинні стани",      "chart_preview:halfhour")],
        [_btn("← Назад", "admin_chart_render")],
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


def get_broadcast_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("❌ Скасувати", "broadcast_cancel")]])
