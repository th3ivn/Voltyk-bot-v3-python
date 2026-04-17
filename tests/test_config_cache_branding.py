"""Unit tests for bot/config.py, bot/services/chart_cache.py,
and bot/services/branding.py."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import bot.services.chart_cache as chart_cache
from bot.services.chart_cache import CHART_TTL_S, CHART_VERSION

# ===========================================================================
# bot/config.py — Settings
# ===========================================================================


class TestSettingsParseAdminIds:
    """Tests for the parse_admin_ids field_validator."""

    def test_csv_string(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token", ADMIN_IDS="1,2,3")
        assert s.ADMIN_IDS == [1, 2, 3]

    def test_csv_string_with_spaces(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token", ADMIN_IDS=" 1 , 2 , 3 ")
        assert s.ADMIN_IDS == [1, 2, 3]

    def test_empty_string_returns_empty_list(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token", ADMIN_IDS="")
        assert s.ADMIN_IDS == []

    def test_list_passthrough(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token", ADMIN_IDS=[1, 2])
        assert s.ADMIN_IDS == [1, 2]

    def test_single_value_string(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token", ADMIN_IDS="42")
        assert s.ADMIN_IDS == [42]


class TestSettingsAdminIdsSet:
    """Tests for model_post_init building _admin_ids_set."""

    def test_owner_and_admins_combined(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token", OWNER_ID=1, ADMIN_IDS=[2, 3])
        assert s._admin_ids_set == frozenset({1, 2, 3})

    def test_no_owner_only_admins(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token", ADMIN_IDS=[2, 3])
        assert s._admin_ids_set == frozenset({2, 3})

    def test_no_owner_no_admins_empty_frozenset(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token", ADMIN_IDS=[])
        assert s._admin_ids_set == frozenset()

    def test_owner_without_admins_in_set(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token", OWNER_ID=99, ADMIN_IDS=[])
        assert 99 in s._admin_ids_set


class TestSettingsIsAdmin:
    """Tests for is_admin()."""

    def test_admin_id_returns_true(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token", ADMIN_IDS=[100, 200])
        assert s.is_admin(100) is True
        assert s.is_admin(200) is True

    def test_unknown_user_returns_false(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token", ADMIN_IDS=[100])
        assert s.is_admin(999) is False

    def test_owner_is_also_admin(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token", OWNER_ID=1, ADMIN_IDS=[])
        assert s.is_admin(1) is True

    def test_empty_admins_returns_false(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token", ADMIN_IDS=[])
        assert s.is_admin(42) is False


class TestSettingsIsOwner:
    """Tests for is_owner()."""

    def test_owner_id_returns_true(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token", OWNER_ID=42)
        assert s.is_owner(42) is True

    def test_wrong_user_returns_false(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token", OWNER_ID=42)
        assert s.is_owner(999) is False

    def test_no_owner_returns_false(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token")
        assert s.is_owner(42) is False

    def test_admin_id_not_owner(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token", OWNER_ID=1, ADMIN_IDS=[2])
        assert s.is_owner(2) is False


class TestSettingsAllAdminIds:
    """Tests for all_admin_ids property."""

    def test_contains_owner_and_admins(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token", OWNER_ID=1, ADMIN_IDS=[2, 3])
        assert set(s.all_admin_ids) == {1, 2, 3}

    def test_empty_when_no_owner_no_admins(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token", ADMIN_IDS=[])
        assert s.all_admin_ids == []


class TestSettingsTimezone:
    """Tests for timezone property."""

    def test_default_timezone_is_kyiv(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token")
        assert s.timezone == ZoneInfo("Europe/Kyiv")

    def test_custom_timezone(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="test-token", TZ="UTC")
        assert s.timezone == ZoneInfo("UTC")


class TestSettingsSyncDatabaseUrl:
    """Tests for sync_database_url property."""

    def test_strips_asyncpg_suffix(self):
        from bot.config import Settings

        s = Settings(
            BOT_TOKEN="test-token",
            DATABASE_URL="postgresql+asyncpg://localhost/db",
        )
        assert s.sync_database_url == "postgresql://localhost/db"

    def test_no_asyncpg_unchanged(self):
        from bot.config import Settings

        s = Settings(
            BOT_TOKEN="test-token",
            DATABASE_URL="postgresql://localhost/db",
        )
        assert s.sync_database_url == "postgresql://localhost/db"


# ===========================================================================
# bot/services/chart_cache.py — Redis chart cache
# ===========================================================================


class TestChartCacheKey:
    """Tests for _key() helper."""

    def test_key_format(self):
        from bot.services.chart_cache import _key

        assert _key("kyiv", "1.1") == f"chart:v{CHART_VERSION}:kyiv:1.1"

    def test_key_uses_chart_version(self):
        from bot.services.chart_cache import _key

        result = _key("lviv", "2.3")
        assert f"v{CHART_VERSION}" in result
        assert "lviv" in result
        assert "2.3" in result


class TestChartCacheIsUsable:
    """Tests for is_usable()."""

    def setup_method(self):
        chart_cache._redis = None

    def teardown_method(self):
        chart_cache._redis = None

    def test_false_when_redis_none(self):
        assert chart_cache.is_usable() is False

    def test_true_when_redis_set(self):
        chart_cache._redis = MagicMock()
        assert chart_cache.is_usable() is True


class TestChartCacheGet:
    """Tests for get()."""

    def setup_method(self):
        chart_cache._redis = None

    def teardown_method(self):
        chart_cache._redis = None

    async def test_returns_none_when_redis_none(self):
        result = await chart_cache.get("kyiv", "1.1")
        assert result is None

    async def test_returns_bytes_from_redis(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"png-data")
        chart_cache._redis = mock_redis

        result = await chart_cache.get("kyiv", "1.1")

        assert result == b"png-data"
        mock_redis.get.assert_called_once_with(f"chart:v{CHART_VERSION}:kyiv:1.1")

    async def test_returns_none_on_redis_error(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=Exception("connection error"))
        chart_cache._redis = mock_redis

        result = await chart_cache.get("kyiv", "1.1")

        assert result is None

    async def test_returns_none_when_key_missing(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        chart_cache._redis = mock_redis

        result = await chart_cache.get("kyiv", "9.9")

        assert result is None


class TestChartCacheStore:
    """Tests for store()."""

    def setup_method(self):
        chart_cache._redis = None

    def teardown_method(self):
        chart_cache._redis = None

    async def test_noop_when_redis_none(self):
        # Should complete without error
        await chart_cache.store("kyiv", "1.1", b"data")

    async def test_calls_setex_with_correct_args(self):
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()
        chart_cache._redis = mock_redis

        await chart_cache.store("kyiv", "1.1", b"png-bytes")

        mock_redis.setex.assert_called_once_with(
            f"chart:v{CHART_VERSION}:kyiv:1.1",
            CHART_TTL_S,
            b"png-bytes",
        )

    async def test_catches_setex_errors(self):
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock(side_effect=Exception("write error"))
        chart_cache._redis = mock_redis

        # Should not raise
        await chart_cache.store("kyiv", "1.1", b"data")


class TestChartCacheDelete:
    """Tests for delete()."""

    def setup_method(self):
        chart_cache._redis = None

    def teardown_method(self):
        chart_cache._redis = None

    async def test_noop_when_redis_none(self):
        await chart_cache.delete("kyiv", "1.1")

    async def test_calls_redis_delete(self):
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()
        chart_cache._redis = mock_redis

        await chart_cache.delete("kyiv", "1.1")

        mock_redis.delete.assert_called_once_with(f"chart:v{CHART_VERSION}:kyiv:1.1")

    async def test_catches_delete_errors(self):
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(side_effect=Exception("delete error"))
        chart_cache._redis = mock_redis

        # Should not raise
        await chart_cache.delete("kyiv", "1.1")


class TestChartCacheInit:
    """Tests for init()."""

    def setup_method(self):
        chart_cache._redis = None

    def teardown_method(self):
        chart_cache._redis = None

    async def test_creates_client_and_pings(self):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()

        with patch("bot.services.chart_cache.aioredis.from_url", return_value=mock_redis) as mock_from_url:
            await chart_cache.init()

        mock_from_url.assert_called_once()
        mock_redis.ping.assert_called_once()
        assert chart_cache._redis is mock_redis

    async def test_init_handles_ping_failure(self):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=Exception("connection refused"))

        with patch("bot.services.chart_cache.aioredis.from_url", return_value=mock_redis):
            # Should not raise even if ping fails
            await chart_cache.init()

        assert chart_cache._redis is mock_redis

    async def test_init_passes_correct_url(self):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()

        with patch("bot.services.chart_cache.aioredis.from_url", return_value=mock_redis) as mock_from_url:
            with patch("bot.services.chart_cache.settings") as mock_settings:
                mock_settings.REDIS_URL = "redis://testhost:6379/1"
                await chart_cache.init()

        call_kwargs = mock_from_url.call_args
        assert call_kwargs[0][0] == "redis://testhost:6379/1"


class TestChartCacheClose:
    """Tests for close()."""

    def setup_method(self):
        chart_cache._redis = None

    def teardown_method(self):
        chart_cache._redis = None

    async def test_calls_aclose_and_sets_none(self):
        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock()
        chart_cache._redis = mock_redis

        await chart_cache.close()

        mock_redis.aclose.assert_called_once()
        assert chart_cache._redis is None

    async def test_safe_when_already_none(self):
        # Should not raise when _redis is None
        await chart_cache.close()
        assert chart_cache._redis is None

    async def test_catches_aclose_errors(self):
        mock_redis = AsyncMock()
        mock_redis.aclose = AsyncMock(side_effect=Exception("close error"))
        chart_cache._redis = mock_redis

        # Should not raise
        await chart_cache.close()

        assert chart_cache._redis is None


# ===========================================================================
# bot/services/branding.py — apply_channel_branding
# ===========================================================================


def _make_cc(**kwargs):
    defaults = dict(
        channel_id=-1001234567890,
        channel_user_title="My Title",
        channel_user_description="My description",
        channel_title=None,
        channel_description=None,
        channel_branding_updated_at=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_bot():
    bot = AsyncMock()
    bot.get_me = AsyncMock(return_value=SimpleNamespace(username="voltyk_bot"))
    bot.set_chat_title = AsyncMock()
    bot.set_chat_description = AsyncMock()
    bot.set_chat_photo = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


class TestApplyChannelBrandingEarlyReturn:
    """Tests for early-return conditions."""

    async def test_returns_early_if_cc_none(self):
        bot = _make_bot()
        from bot.services.branding import apply_channel_branding

        await apply_channel_branding(bot, None)

        bot.get_me.assert_not_called()

    async def test_returns_early_if_channel_id_none(self):
        bot = _make_bot()
        cc = _make_cc(channel_id=None)
        from bot.services.branding import apply_channel_branding

        await apply_channel_branding(bot, cc)

        bot.get_me.assert_not_called()

    async def test_returns_early_if_channel_id_zero(self):
        bot = _make_bot()
        cc = _make_cc(channel_id=0)
        from bot.services.branding import apply_channel_branding

        await apply_channel_branding(bot, cc)

        bot.get_me.assert_not_called()


class TestApplyChannelBrandingTitle:
    """Tests for channel title setting."""

    async def test_sets_chat_title(self):
        bot = _make_bot()
        cc = _make_cc()
        from bot.services.branding import apply_channel_branding

        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_path:
            mock_path.exists.return_value = False
            await apply_channel_branding(bot, cc)

        bot.set_chat_title.assert_called_once()
        assert bot.set_chat_title.call_args[0][0] == cc.channel_id

    async def test_updates_cc_channel_title_on_success(self):
        bot = _make_bot()
        cc = _make_cc(channel_user_title="Kyiv 1.1")
        from bot.services.branding import apply_channel_branding

        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_path:
            mock_path.exists.return_value = False
            await apply_channel_branding(bot, cc)

        assert cc.channel_title is not None

    async def test_title_failure_does_not_prevent_further_steps(self):
        bot = _make_bot()
        bot.set_chat_title = AsyncMock(side_effect=Exception("title error"))
        cc = _make_cc()
        from bot.services.branding import apply_channel_branding

        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_path:
            mock_path.exists.return_value = False
            # Should not raise
            await apply_channel_branding(bot, cc)

        # Description should still be attempted
        bot.set_chat_description.assert_called_once()
        # Timestamp should still be updated
        assert cc.channel_branding_updated_at is not None


class TestApplyChannelBrandingDescription:
    """Tests for channel description setting."""

    async def test_sets_chat_description_when_present(self):
        bot = _make_bot()
        cc = _make_cc(channel_user_description="Some description")
        from bot.services.branding import apply_channel_branding

        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_path:
            mock_path.exists.return_value = False
            await apply_channel_branding(bot, cc)

        bot.set_chat_description.assert_called_once()

    async def test_skips_description_when_none(self):
        bot = _make_bot()
        cc = _make_cc(channel_user_description=None)
        from bot.services.branding import apply_channel_branding

        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_path:
            mock_path.exists.return_value = False
            await apply_channel_branding(bot, cc)

        bot.set_chat_description.assert_not_called()

    async def test_updates_cc_channel_description_on_success(self):
        bot = _make_bot()
        cc = _make_cc(channel_user_description="Some desc")
        from bot.services.branding import apply_channel_branding

        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_path:
            mock_path.exists.return_value = False
            await apply_channel_branding(bot, cc)

        assert cc.channel_description is not None

    async def test_description_failure_does_not_prevent_further_steps(self):
        bot = _make_bot()
        bot.set_chat_description = AsyncMock(side_effect=Exception("desc error"))
        cc = _make_cc(channel_user_description="Some desc")
        from bot.services.branding import apply_channel_branding

        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_path:
            mock_path.exists.return_value = True
            with patch("bot.services.branding.FSInputFile"):
                await apply_channel_branding(bot, cc)

        # Photo should still be attempted
        bot.set_chat_photo.assert_called_once()
        assert cc.channel_branding_updated_at is not None


class TestApplyChannelBrandingPhoto:
    """Tests for channel photo setting."""

    async def test_sets_chat_photo_when_file_exists(self):
        bot = _make_bot()
        cc = _make_cc()
        from bot.services.branding import apply_channel_branding

        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_path, \
             patch("bot.services.branding.FSInputFile") as mock_fsinput:
            mock_path.exists.return_value = True
            await apply_channel_branding(bot, cc)

        bot.set_chat_photo.assert_called_once()
        mock_fsinput.assert_called_once_with(mock_path)

    async def test_skips_photo_when_file_missing(self):
        bot = _make_bot()
        cc = _make_cc()
        from bot.services.branding import apply_channel_branding

        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_path:
            mock_path.exists.return_value = False
            await apply_channel_branding(bot, cc)

        bot.set_chat_photo.assert_not_called()

    async def test_photo_failure_does_not_prevent_rest(self):
        bot = _make_bot()
        bot.set_chat_photo = AsyncMock(side_effect=Exception("photo error"))
        cc = _make_cc()
        from bot.services.branding import apply_channel_branding

        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_path, \
             patch("bot.services.branding.FSInputFile"):
            mock_path.exists.return_value = True
            # Should not raise
            await apply_channel_branding(bot, cc, send_welcome=True, queue="1.1")

        # Timestamp and welcome should still be processed
        assert cc.channel_branding_updated_at is not None
        bot.send_message.assert_called_once()


class TestApplyChannelBrandingTimestamp:
    """Tests for channel_branding_updated_at update."""

    async def test_updates_timestamp(self):
        bot = _make_bot()
        cc = _make_cc()
        from bot.services.branding import apply_channel_branding

        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_path:
            mock_path.exists.return_value = False
            await apply_channel_branding(bot, cc)

        assert cc.channel_branding_updated_at is not None


class TestApplyChannelBrandingWelcome:
    """Tests for welcome message sending."""

    async def test_sends_welcome_when_send_welcome_true_and_queue_provided(self):
        bot = _make_bot()
        cc = _make_cc()
        from bot.services.branding import apply_channel_branding

        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_path:
            mock_path.exists.return_value = False
            await apply_channel_branding(bot, cc, send_welcome=True, queue="1.1")

        bot.send_message.assert_called_once()
        assert bot.send_message.call_args[0][0] == cc.channel_id
        assert bot.send_message.call_args[1].get("parse_mode") == "HTML"

    async def test_no_welcome_when_queue_none(self):
        bot = _make_bot()
        cc = _make_cc()
        from bot.services.branding import apply_channel_branding

        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_path:
            mock_path.exists.return_value = False
            await apply_channel_branding(bot, cc, send_welcome=True, queue=None)

        bot.send_message.assert_not_called()

    async def test_no_welcome_when_send_welcome_false(self):
        bot = _make_bot()
        cc = _make_cc()
        from bot.services.branding import apply_channel_branding

        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_path:
            mock_path.exists.return_value = False
            await apply_channel_branding(bot, cc, send_welcome=False, queue="1.1")

        bot.send_message.assert_not_called()

    async def test_welcome_failure_is_caught(self):
        bot = _make_bot()
        bot.send_message = AsyncMock(side_effect=Exception("send error"))
        cc = _make_cc()
        from bot.services.branding import apply_channel_branding

        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_path:
            mock_path.exists.return_value = False
            # Should not raise
            await apply_channel_branding(bot, cc, send_welcome=True, queue="1.1")

    async def test_welcome_with_region_and_has_ip(self):
        bot = _make_bot()
        cc = _make_cc()
        from bot.services.branding import apply_channel_branding

        with patch("bot.services.branding._CHANNEL_PHOTO") as mock_path:
            mock_path.exists.return_value = False
            await apply_channel_branding(
                bot, cc, send_welcome=True, queue="1.1", region="kyiv", has_ip=True
            )

        bot.send_message.assert_called_once()
        message_text = bot.send_message.call_args[0][1]
        # Message should mention the queue
        assert "1.1" in message_text
        # has_ip=True adds a power notification line
        assert "⚡" in message_text
