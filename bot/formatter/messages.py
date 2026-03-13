from __future__ import annotations

from bot.constants.regions import REGIONS


def has_any_notification_enabled(ns) -> bool:
    if ns is None:
        return False
    return any([
        ns.notify_schedule_changes,
        ns.notify_remind_off,
        ns.notify_fact_off,
        ns.notify_remind_on,
        ns.notify_fact_on,
    ])


def format_live_status_message(user, region_name: str | None = None) -> str:
    if region_name is None:
        r = REGIONS.get(user.region)
        region_name = r.name if r else user.region

    msg = ""
    has_ip = bool(user.router_ip)
    has_channel = bool(user.channel_config and user.channel_config.channel_id)
    ns = user.notification_settings
    notifications_enabled = has_any_notification_enabled(ns)
    power_tracking = user.power_tracking

    if has_ip and power_tracking and power_tracking.power_state:
        power_on = power_tracking.power_state == "on"
        msg += "🟢 Світло зараз: Є\n" if power_on else "🔴 Світло зараз: Немає\n"
        if power_tracking.power_changed_at:
            msg += f"🕓 Оновлено: {power_tracking.power_changed_at.strftime('%H:%M')}\n\n"
        else:
            msg += "\n"
    elif has_ip:
        msg += "⚪ Світло зараз: Невідомо\n\n"

    msg += f"📍 <b>{region_name} · {user.queue}</b>\n\n"
    msg += f"📡 IP: {'підключено ✅' if has_ip else 'не підключено 😕'}\n"
    msg += f"📺 Канал: {'підключено ✅' if has_channel else 'не підключено'}\n"
    msg += f"🔔 Сповіщення: {'увімкнено ✅' if notifications_enabled else 'вимкнено'}\n"

    if not has_ip:
        msg += "\n<i>💡 Додайте IP для моніторингу світла</i>"
    if has_ip and notifications_enabled:
        msg += "\n✅ Моніторинг активний"

    return msg


def format_main_menu_message(user) -> str:
    r = REGIONS.get(user.region)
    region_name = r.name if r else user.region
    has_channel = bool(user.channel_config and user.channel_config.channel_id)
    ns = user.notification_settings
    notifications_enabled = has_any_notification_enabled(ns)

    channel_text = "підключено ✅" if has_channel else "не підключено"
    notif_text = "увімкнено ✅" if notifications_enabled else "вимкнено"

    return (
        f"🏠 Головне меню\n\n"
        f"📍 Регіон: {region_name} • {user.queue}\n"
        f"📺 Канал: {channel_text}\n"
        f"🔔 Сповіщення: {notif_text}\n"
    )


def build_notification_settings_message(ns) -> str:
    def _check(v: bool) -> str:
        return "✅" if v else "❌"

    msg = "🔔 Керування сповіщеннями\n\n"
    msg += f"📈 Оновлення графіків — {_check(ns.notify_schedule_changes)}\n\n"
    msg += "⏳ Нагадування про події перед (вимкнення / відновлення):\n"
    msg += f"├ За 1 год — {_check(ns.remind_1h)}\n"
    msg += f"├ За 30 хв — {_check(ns.remind_30m)}\n"
    msg += f"├ За 15 хв — {_check(ns.remind_15m)}\n"
    msg += f"└ Фактично за IP-адресою — {_check(ns.notify_fact_off)}\n"
    return msg


def build_channel_notification_message(cc) -> str:
    def _check(v: bool) -> str:
        return "✅" if v else "❌"

    msg = "📺 Сповіщення каналу\n\n"
    msg += f"📈 Оновлення графіків — {_check(cc.ch_notify_schedule)}\n\n"
    msg += "⏳ Нагадування про події перед (вимкнення / відновлення):\n"
    msg += f"├ За 1 год — {_check(cc.ch_remind_1h)}\n"
    msg += f"├ За 30 хв — {_check(cc.ch_remind_30m)}\n"
    msg += f"├ За 15 хв — {_check(cc.ch_remind_15m)}\n"
    msg += f"└ Фактично за IP-адресою — {_check(cc.ch_notify_fact_off)}\n"
    return msg
