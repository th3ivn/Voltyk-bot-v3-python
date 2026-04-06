from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

from bot.db.models import UserChannelConfig
from bot.utils.branding import (
    build_channel_description,
    build_channel_title,
    get_channel_welcome_message,
)
from bot.utils.logger import get_logger

logger = get_logger(__name__)

_CHANNEL_PHOTO = Path(__file__).parents[2] / "assets" / "channel_photo.jpg"


async def apply_channel_branding(
    bot: Bot | None,
    cc: UserChannelConfig,
    *,
    send_welcome: bool = False,
    queue: str | None = None,
    region: str | None = None,
    has_ip: bool = False,
) -> None:
    """Apply branding to a Telegram channel and update the config record.

    Args:
        bot: Aiogram Bot instance.
        cc: UserChannelConfig ORM object (mutated in-place).
        send_welcome: Send the one-time welcome message (first-time setup only).
        queue: Required when send_welcome=True.
    """
    if not bot or not cc or not cc.channel_id:
        return

    me = await bot.get_me()

    full_title = build_channel_title(cc.channel_user_title or "")
    try:
        await bot.set_chat_title(cc.channel_id, full_title)
        cc.channel_title = full_title
    except Exception as e:
        logger.warning("Failed to set channel title for %s: %s", cc.channel_id, e)

    full_desc = build_channel_description(cc.channel_user_description, me.username)
    if full_desc:
        try:
            await bot.set_chat_description(cc.channel_id, full_desc)
            cc.channel_description = full_desc
        except Exception as e:
            logger.warning("Failed to set channel description for %s: %s", cc.channel_id, e)

    if _CHANNEL_PHOTO.exists():
        try:
            await bot.set_chat_photo(cc.channel_id, FSInputFile(_CHANNEL_PHOTO))
        except Exception as e:
            logger.warning("Failed to set channel photo for %s: %s", cc.channel_id, e)

    cc.channel_branding_updated_at = datetime.now(timezone.utc)

    if send_welcome and queue:
        try:
            await bot.send_message(
                cc.channel_id,
                get_channel_welcome_message(queue, me.username, region=region, has_ip=has_ip),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.warning("Failed to send welcome message to %s: %s", cc.channel_id, e)
