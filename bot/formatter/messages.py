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
    def _c(v: bool) -> str:
        return "✅" if v else "❌"

    return (
        '<tg-emoji emoji-id="5262598817626234330">🔔</tg-emoji> Керування сповіщеннями\n\n'
        f'<tg-emoji emoji-id="5231200819986047254">📈</tg-emoji> Оновлення графіків — {_c(ns.notify_schedule_changes)}\n\n'
        f'<tg-emoji emoji-id="5451732530048802485">⏳</tg-emoji> Нагадування про події перед (вимкнення / відновлення):\n'
        f"├ За 1 год — {_c(ns.remind_1h)}\n"
        f"├ За 30 хв — {_c(ns.remind_30m)}\n"
        f"├ За 15 хв — {_c(ns.remind_15m)}\n"
        f"└ Фактично за IP-адресою — {_c(ns.notify_fact_off)}\n"
    )


def build_channel_notification_message(cc) -> str:
    def _c(v: bool) -> str:
        return "✅" if v else "❌"

    return (
        f'<tg-emoji emoji-id="5424818078833715060">📺</tg-emoji> Сповіщення каналу\n\n'
        f'<tg-emoji emoji-id="5231200819986047254">📈</tg-emoji> Оновлення графіків — {_c(cc.ch_notify_schedule)}\n\n'
        f'<tg-emoji emoji-id="5451732530048802485">⏳</tg-emoji> Нагадування про події перед (вимкнення / відновлення):\n'
        f"├ За 1 год — {_c(cc.ch_remind_1h)}\n"
        f"├ За 30 хв — {_c(cc.ch_remind_30m)}\n"
        f"├ За 15 хв — {_c(cc.ch_remind_15m)}\n"
        f"└ Фактично за IP-адресою — {_c(cc.ch_notify_fact_off)}\n"
    )
