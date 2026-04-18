"""Tests for bot/config.py — uncovered branches (lines 91, 94-95, 130)."""
from __future__ import annotations

import importlib
import sys

import pytest


class TestParseAdminIds:
    """field_validator 'parse_admin_ids' edge cases."""

    def _make_settings(self, admin_ids_raw: str):
        from bot.config import Settings

        return Settings(
            BOT_TOKEN="test:token",
            DATABASE_URL="postgresql+asyncpg://u:p@localhost/db",
            ADMIN_IDS=admin_ids_raw,
        )

    def test_empty_segment_skipped(self):
        """Line 91: empty segment after split (e.g. trailing comma) → continue."""
        s = self._make_settings("123,,456")
        assert s.ADMIN_IDS == [123, 456]

    def test_leading_trailing_comma_skipped(self):
        """Line 91: leading/trailing comma → empty segment → continue."""
        s = self._make_settings(",789,")
        assert s.ADMIN_IDS == [789]

    def test_invalid_non_integer_id_skipped_with_warning(self):
        """Lines 94-95: non-integer admin ID → warning logged, entry skipped."""
        s = self._make_settings("111,abc,222")
        assert s.ADMIN_IDS == [111, 222]

    def test_all_invalid_returns_empty(self):
        """Lines 94-95: all non-integer → empty list."""
        s = self._make_settings("foo,bar")
        assert s.ADMIN_IDS == []

    def test_list_passthrough(self):
        """mode='before' with list input → returned as-is."""
        from bot.config import Settings

        s = Settings(
            BOT_TOKEN="test:token",
            DATABASE_URL="postgresql+asyncpg://u:p@localhost/db",
            ADMIN_IDS=[10, 20],
        )
        assert s.ADMIN_IDS == [10, 20]

    def test_empty_string_returns_empty_list(self):
        """Empty ADMIN_IDS string → empty list (no iterations)."""
        s = self._make_settings("")
        assert s.ADMIN_IDS == []


class TestWebhookSecretValidation:
    """Module-level guard: USE_WEBHOOK=True without WEBHOOK_SECRET raises ValueError."""

    def test_webhook_without_secret_raises_at_module_level(self, monkeypatch):
        """Line 130: reload config with USE_WEBHOOK=True + empty secret → ValueError."""
        monkeypatch.setenv("BOT_TOKEN", "test:token")
        monkeypatch.setenv("USE_WEBHOOK", "true")
        monkeypatch.setenv("WEBHOOK_SECRET", "")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
        # Remove cached module so import_module re-executes module-level guard
        monkeypatch.delitem(sys.modules, "bot.config", raising=False)

        with pytest.raises(ValueError, match="WEBHOOK_SECRET is required"):
            importlib.import_module("bot.config")

    def test_webhook_with_secret_does_not_raise(self):
        """USE_WEBHOOK=True + non-empty WEBHOOK_SECRET → no error."""
        from bot.config import Settings

        s = Settings(
            BOT_TOKEN="test:token",
            DATABASE_URL="postgresql+asyncpg://u:p@localhost/db",
            USE_WEBHOOK=True,
            WEBHOOK_SECRET="my-secret-token",
        )
        assert s.USE_WEBHOOK is True
        assert s.WEBHOOK_SECRET == "my-secret-token"

    def test_no_webhook_no_secret_no_raise(self):
        """USE_WEBHOOK=False + no secret → guard not triggered."""
        from bot.config import Settings

        s = Settings(
            BOT_TOKEN="test:token",
            DATABASE_URL="postgresql+asyncpg://u:p@localhost/db",
            USE_WEBHOOK=False,
            WEBHOOK_SECRET="",
        )
        assert s.USE_WEBHOOK is False


class TestBotTokenValidation:
    """field_validator 'validate_bot_token' edge cases."""

    def test_empty_string_raises(self):
        from pydantic import ValidationError

        from bot.config import Settings

        with pytest.raises(ValidationError, match="BOT_TOKEN"):
            Settings(BOT_TOKEN="", DATABASE_URL="postgresql+asyncpg://u:p@localhost/db")

    def test_whitespace_only_raises(self):
        from pydantic import ValidationError

        from bot.config import Settings

        with pytest.raises(ValidationError, match="BOT_TOKEN"):
            Settings(BOT_TOKEN="   ", DATABASE_URL="postgresql+asyncpg://u:p@localhost/db")

    def test_missing_colon_raises(self):
        from pydantic import ValidationError

        from bot.config import Settings

        with pytest.raises(ValidationError, match="BOT_TOKEN"):
            Settings(BOT_TOKEN="invalidtoken", DATABASE_URL="postgresql+asyncpg://u:p@localhost/db")

    def test_valid_token_accepted(self):
        from bot.config import Settings

        s = Settings(BOT_TOKEN="123456:ABCDEFabcdef", DATABASE_URL="postgresql+asyncpg://u:p@localhost/db")
        assert s.BOT_TOKEN == "123456:ABCDEFabcdef"


class TestTimezoneValidation:
    """model_post_init ZoneInfo validation."""

    def test_invalid_tz_raises_value_error(self):
        from pydantic import ValidationError

        from bot.config import Settings

        with pytest.raises((ValidationError, ValueError), match="Invalid timezone"):
            Settings(
                BOT_TOKEN="test:token",
                DATABASE_URL="postgresql+asyncpg://u:p@localhost/db",
                TZ="Not/AReal/Timezone",
            )

    def test_valid_tz_accepted(self):
        from bot.config import Settings

        s = Settings(
            BOT_TOKEN="test:token",
            DATABASE_URL="postgresql+asyncpg://u:p@localhost/db",
            TZ="Europe/Kyiv",
        )
        assert str(s.timezone) == "Europe/Kyiv"


class TestWebhookSecretWhitespace:
    """Module-level guard handles whitespace-only WEBHOOK_SECRET."""

    def test_whitespace_only_secret_raises(self, monkeypatch):
        import sys

        monkeypatch.setenv("BOT_TOKEN", "test:token")
        monkeypatch.setenv("USE_WEBHOOK", "true")
        monkeypatch.setenv("WEBHOOK_SECRET", "   ")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
        monkeypatch.delitem(sys.modules, "bot.config", raising=False)

        with pytest.raises(ValueError, match="WEBHOOK_SECRET is required"):
            importlib.import_module("bot.config")


class TestDefaultCredentialWarnings:
    """model_validator: warnings when default DB/Redis URLs are used (lines 111, 115)."""

    def test_database_url_default_logs_warning(self):
        """Line 111: DATABASE_URL equals hardcoded default → warning logged."""
        from unittest.mock import patch

        from bot.config import Settings

        with patch("bot.config.logger") as mock_log:
            Settings(
                BOT_TOKEN="test:token",
                DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/voltyk",
                REDIS_URL="redis://custom:6379/0",
            )

        calls = [str(c) for c in mock_log.warning.call_args_list]
        assert any("DATABASE_URL" in c for c in calls)
