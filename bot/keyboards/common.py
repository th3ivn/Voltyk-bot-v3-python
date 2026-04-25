from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Persistent setting key used by admin panel:
# true  -> use Telegram custom button icons (premium)
# false -> fall back to regular text emoji only
BUTTON_EMOJI_MODE_SETTING_KEY = "button_custom_emoji_enabled"
_button_custom_emoji_enabled = True

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

_FALLBACK_TEXT_EMOJI_BY_ID: dict[str, str] = {
    E_HELP: "❓",
    E_ALERTS: "🔔",
    E_CHANNEL: "📺",
    E_BOT_SETTINGS: "⚙️",
    E_RESUME: "▶️",
    E_PAUSE_CHANNEL: "⏸️",
    E_SCHEDULE_SEC: "📊",
    E_SCHEDULE_CHANGES: "📈",
    E_BOT_NOTIF: "📱",
    E_FACT: "⚡",
    E_REGION: "📍",
    E_REFRESH: "🔄",
    E_INSTRUCTION: "📍",
    E_INSTR_HELP: "📘",
    E_IP_SECTION: "📡",
    E_CHANNEL_SECTION: "📺",
    E_NOTIF_SECTION: "🔔",
    E_ADMIN: "👑",
    E_DELETE_DATA: "🗑",
    E_CHANGE_IP: "✏️",
    E_DELETE_IP: "🗑",
    E_PING_CHECK: "📡",
    E_SUPPORT: "💬",
    E_FAQ: "❓",
    E_NEWS: "📺",
    E_DISCUSS: "💬",
    E_SUCCESS: "✅",
}


def set_button_custom_emoji_enabled(enabled: bool) -> None:
    """Toggle custom emoji icons for inline keyboard buttons at runtime."""
    global _button_custom_emoji_enabled
    _button_custom_emoji_enabled = enabled


def is_button_custom_emoji_enabled() -> bool:
    """Return whether custom emoji icons are currently enabled for buttons."""
    return _button_custom_emoji_enabled


def _with_fallback_text_emoji(text: str, emoji_id: str | None) -> str:
    """Prefix plain button text with a standard emoji when custom icons are disabled."""
    if _button_custom_emoji_enabled or not emoji_id:
        return text
    lowered = text.lower()
    if "новини" in lowered:
        fallback_emoji = "📰"
    elif "обговорення" in lowered or "підтрим" in lowered:
        fallback_emoji = "💬"
    else:
        fallback_emoji = _FALLBACK_TEXT_EMOJI_BY_ID.get(emoji_id)
    if not fallback_emoji:
        return text
    # If the button text already starts with a symbol/emoji (e.g. "👀 Графік"),
    # avoid double prefixing.
    first_char = text[:1]
    if first_char and not first_char.isalnum():
        return text
    return f"{fallback_emoji} {text}"


def _btn(
    text: str,
    callback_data: str,
    emoji_id: str | None = None,
    style: str | None = None,
    **kwargs,
) -> InlineKeyboardButton:
    params: dict = {"text": _with_fallback_text_emoji(text, emoji_id), "callback_data": callback_data, **kwargs}
    if emoji_id and _button_custom_emoji_enabled:
        params["icon_custom_emoji_id"] = emoji_id
    if style:
        params["style"] = style
    return InlineKeyboardButton(**params)


def _url_btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def _url_btn_with_emoji(text: str, url: str, emoji_id: str | None = None) -> InlineKeyboardButton:
    params: dict = {"text": _with_fallback_text_emoji(text, emoji_id), "url": url}
    if emoji_id and _button_custom_emoji_enabled:
        params["icon_custom_emoji_id"] = emoji_id
    return InlineKeyboardButton(**params)


def _nav_row(back_cb: str | None = None, *, menu: bool = True) -> list[InlineKeyboardButton]:
    """Return a navigation button row with an optional Back button and/or Menu button.

    Args:
        back_cb: Callback data for the ``← Назад`` button. Omitted when *None*.
        menu: Include the ``⤴ Меню`` button (default True).
    """
    row: list[InlineKeyboardButton] = []
    if back_cb is not None:
        row.append(_btn("← Назад", back_cb))
    if menu:
        row.append(_btn("⤴ Меню", "back_to_main"))
    return row


def get_error_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn("🔄 Спробувати ще", "back_to_main")],
    ])


def get_understood_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        _btn("Зрозуміло", "reminder_dismiss", E_SUCCESS),
    ]])
