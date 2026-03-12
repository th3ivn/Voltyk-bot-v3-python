"""Inline keyboard builders for Voltyk Bot.

All keyboards are built from scratch to match the original bot's UI exactly.
Button labels and layouts are in Ukrainian as per UI/UX parity requirements.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.constants.regions import get_queues_for_region

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_QUEUES_PER_PAGE = 12  # standard (non-Kyiv) queues fit on one page
_KYIV_PAGE_SIZE = 12   # items per pagination page for Kyiv extra queues


# ---------------------------------------------------------------------------
# Region keyboard
# ---------------------------------------------------------------------------


def get_region_keyboard() -> InlineKeyboardMarkup:
    """Return the region selection inline keyboard.

    Layout:
        Row 1: [Київ]  [Київщина]
        Row 2: [Дніпропетровщина]  [Одещина]
        Row 3: [🏙 Запропонувати регіон]
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Київ", callback_data="region_kyiv"),
        InlineKeyboardButton(text="Київщина", callback_data="region_kyiv-region"),
    )
    builder.row(
        InlineKeyboardButton(
            text="Дніпропетровщина", callback_data="region_dnipro"
        ),
        InlineKeyboardButton(text="Одещина", callback_data="region_odesa"),
    )
    builder.row(
        InlineKeyboardButton(
            text="🏙 Запропонувати регіон", callback_data="suggest_region"
        )
    )
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Queue keyboard
# ---------------------------------------------------------------------------


def get_queue_keyboard(region: str | None = None, page: int = 1) -> InlineKeyboardMarkup:
    """Return the queue selection inline keyboard for the given region.

    For non-Kyiv regions all 12 queues fit on a single page (3 per row)
    with a [← Назад] button at the bottom.

    For Kyiv:
      - Page 1  → 12 standard queues (4 per row) + [Інші черги →] + [← Назад]
      - Pages 2+ → paginated extra queues (4 per row) with [← Назад] / [Далі →]

    Args:
        region: Region code string (e.g. ``"kyiv"``).  ``None`` defaults to
                standard 12 queues.
        page:   Current page number (1-based).  Only meaningful for Kyiv.
    """
    queues = get_queues_for_region(region or "")
    builder = InlineKeyboardBuilder()

    is_kyiv = region == "kyiv"

    if not is_kyiv:
        # All 12 queues, 3 per row
        row_buf: list[InlineKeyboardButton] = []
        for q in queues:
            row_buf.append(InlineKeyboardButton(text=q, callback_data=f"queue_{q}"))
            if len(row_buf) == 3:
                builder.row(*row_buf)
                row_buf = []
        if row_buf:
            builder.row(*row_buf)
        builder.row(
            InlineKeyboardButton(text="← Назад", callback_data="back_to_region")
        )
    else:
        standard = queues[:12]  # 1.1–6.2
        extra = queues[12:]     # 7.1–60.1

        if page == 1:
            # 12 standard queues, 4 per row
            row_buf = []
            for q in standard:
                row_buf.append(
                    InlineKeyboardButton(text=q, callback_data=f"queue_{q}")
                )
                if len(row_buf) == 4:
                    builder.row(*row_buf)
                    row_buf = []
            if row_buf:
                builder.row(*row_buf)
            # Navigation: [← Назад]  [Інші черги →]
            builder.row(
                InlineKeyboardButton(text="← Назад", callback_data="back_to_region"),
                InlineKeyboardButton(
                    text="Інші черги →", callback_data="queue_page_2"
                ),
            )
        else:
            # Extra-queue pages (2-based index within extra list)
            per_page = _KYIV_PAGE_SIZE
            offset = (page - 2) * per_page
            page_items = extra[offset: offset + per_page]
            total_extra_pages = -(-len(extra) // per_page)  # ceiling division
            last_page = total_extra_pages + 1  # +1 because page 1 = standard

            row_buf = []
            for q in page_items:
                row_buf.append(
                    InlineKeyboardButton(text=q, callback_data=f"queue_{q}")
                )
                if len(row_buf) == 4:
                    builder.row(*row_buf)
                    row_buf = []
            if row_buf:
                builder.row(*row_buf)

            # Navigation row
            nav: list[InlineKeyboardButton] = []
            prev_page = page - 1
            nav.append(
                InlineKeyboardButton(
                    text="← Назад", callback_data=f"queue_page_{prev_page}"
                )
            )
            if page < last_page:
                nav.append(
                    InlineKeyboardButton(
                        text="Далі →", callback_data=f"queue_page_{page + 1}"
                    )
                )
            builder.row(*nav)

    return builder.as_markup()


# ---------------------------------------------------------------------------
# Confirmation keyboard
# ---------------------------------------------------------------------------


def get_confirm_keyboard() -> InlineKeyboardMarkup:
    """Return the setup-confirmation inline keyboard.

    Layout:
        Row 1: [✓ Підтвердити]
        Row 2: [🔄 Змінити регіон]
        Row 3: [⤴ Меню]
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✓ Підтвердити", callback_data="confirm_setup")
    )
    builder.row(
        InlineKeyboardButton(
            text="🔄 Змінити регіон", callback_data="back_to_region"
        )
    )
    builder.row(
        InlineKeyboardButton(text="⤴ Меню", callback_data="back_to_main")
    )
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Main menu keyboard
# ---------------------------------------------------------------------------


def get_main_menu() -> InlineKeyboardMarkup:
    """Return the main menu inline keyboard shown after registration.

    Layout:
        Row 1: [Графік]  [Допомога]
        Row 2: [Статистика]  [Таймер]
        Row 3: [Налаштування]
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Графік", callback_data="menu_schedule"),
        InlineKeyboardButton(text="Допомога", callback_data="menu_help"),
    )
    builder.row(
        InlineKeyboardButton(text="Статистика", callback_data="menu_stats"),
        InlineKeyboardButton(text="Таймер", callback_data="menu_timer"),
    )
    builder.row(
        InlineKeyboardButton(text="Налаштування", callback_data="menu_settings")
    )
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Blocked user keyboard
# ---------------------------------------------------------------------------


def get_blocked_keyboard() -> InlineKeyboardMarkup:
    """Return the keyboard shown to blocked users.

    Rule #3: blocked users must still see buttons alongside the
    "Ви заблоковані" message.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="📩 Написати адміністратору", callback_data="contact_admin"
        )
    )
    return builder.as_markup()
