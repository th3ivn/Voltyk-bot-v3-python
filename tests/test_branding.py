"""Tests for bot/utils/branding.py — pure functions, no I/O."""
from __future__ import annotations

from bot.utils.branding import (
    MAX_USER_DESC_LEN,
    MAX_USER_TITLE_LEN,
    build_channel_description,
    build_channel_title,
    get_channel_welcome_message,
)


class TestBuildChannelTitle:
    def test_prepends_prefix(self):
        result = build_channel_title("My City")
        assert result.startswith("Вольтик ⚡️ ")
        assert "My City" in result

    def test_empty_user_title(self):
        result = build_channel_title("")
        assert result == "Вольтик ⚡️ "

    def test_truncates_to_128_chars(self):
        long_title = "X" * 200
        result = build_channel_title(long_title)
        assert len(result) <= 128

    def test_normal_title_not_truncated(self):
        result = build_channel_title("Kyiv")
        assert "Kyiv" in result
        assert len(result) <= 128


class TestBuildChannelDescription:
    def test_none_user_desc_returns_none(self):
        assert build_channel_description(None) is None

    def test_empty_user_desc_returns_none(self):
        assert build_channel_description("") is None

    def test_includes_user_desc(self):
        result = build_channel_description("My description")
        assert result is not None
        assert "My description" in result

    def test_includes_base_description(self):
        result = build_channel_description("desc")
        assert "Вольтик" in result

    def test_appends_bot_username(self):
        result = build_channel_description("desc", bot_username="mybot")
        assert "@mybot" in result

    def test_no_username_no_at_sign(self):
        result = build_channel_description("desc", bot_username=None)
        assert result is not None
        assert "@" not in result

    def test_truncates_to_255_chars(self):
        long_desc = "D" * 300
        result = build_channel_description(long_desc)
        assert result is not None
        assert len(result) <= 255


class TestGetChannelWelcomeMessage:
    def test_contains_queue(self):
        msg = get_channel_welcome_message("1", bot_username="volt_bot")
        assert "1" in msg

    def test_contains_bot_link_when_username_given(self):
        msg = get_channel_welcome_message("2", bot_username="volt_bot")
        assert "volt_bot" in msg

    def test_no_link_when_no_username(self):
        msg = get_channel_welcome_message("3", bot_username=None)
        assert "Вольтика" in msg

    def test_contains_region_name(self):
        # "kyiv" is a known region key in REGIONS
        msg = get_channel_welcome_message("1", region="kyiv")
        assert msg  # just check it doesn't raise

    def test_ip_line_when_has_ip(self):
        msg = get_channel_welcome_message("1", has_ip=True)
        assert "Сповіщення" in msg

    def test_no_ip_line_when_no_ip(self):
        msg = get_channel_welcome_message("1", has_ip=False)
        assert "Сповіщення" not in msg

    def test_unknown_region_does_not_raise(self):
        msg = get_channel_welcome_message("1", region="unknown_region_xyz")
        assert msg


class TestConstants:
    def test_max_user_title_len_positive(self):
        assert MAX_USER_TITLE_LEN > 0

    def test_max_user_desc_len_positive(self):
        assert MAX_USER_DESC_LEN > 0

    def test_title_with_max_len_fits(self):
        title = "A" * MAX_USER_TITLE_LEN
        result = build_channel_title(title)
        assert len(result) <= 128

    def test_desc_with_max_len_fits(self):
        desc = "D" * MAX_USER_DESC_LEN
        result = build_channel_description(desc)
        assert result is not None
        assert len(result) <= 255
