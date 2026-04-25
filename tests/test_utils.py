"""Tests for bot/utils/html_to_entities.py, bot/utils/branding.py, and bot/utils/logger.py."""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
import structlog
from aiogram.types import MessageEntity

from bot.utils.branding import (
    _DESC_MAX,
    _TITLE_MAX,
    CHANNEL_DESCRIPTION_BASE,
    CHANNEL_NAME_PREFIX,
    build_channel_description,
    build_channel_title,
    get_channel_welcome_message,
)
from bot.utils.html_to_entities import (
    _utf16_len,
    append_timestamp,
    html_to_entities,
    to_aiogram_entities,
)
from bot.utils.logger import get_logger, setup_logging

# ===========================================================================
# _utf16_len
# ===========================================================================


class TestUtf16Len:
    """Tests for the internal _utf16_len helper."""

    def test_ascii(self):
        assert _utf16_len("abc") == 3

    def test_cyrillic(self):
        # BMP characters — each Cyrillic letter is 1 UTF-16 code unit
        assert _utf16_len("Привіт") == 6

    def test_emoji_surrogate(self):
        # 🔥 U+1F525 is a surrogate pair → 2 UTF-16 code units
        assert _utf16_len("🔥") == 2

    def test_empty(self):
        assert _utf16_len("") == 0

    def test_mixed_bmp_and_supplementary(self):
        # "A🔥B" → 1 + 2 + 1 = 4 code units
        assert _utf16_len("A🔥B") == 4


# ===========================================================================
# html_to_entities
# ===========================================================================


class TestHtmlToEntities:
    """Tests for html_to_entities()."""

    def test_plain_text_no_tags(self):
        text, entities = html_to_entities("hello world")
        assert text == "hello world"
        assert entities == []

    def test_empty_string(self):
        text, entities = html_to_entities("")
        assert text == ""
        assert entities == []

    def test_bold_tag(self):
        text, entities = html_to_entities("<b>bold</b>")
        assert text == "bold"
        assert len(entities) == 1
        assert entities[0]["type"] == "bold"
        assert entities[0]["offset"] == 0
        assert entities[0]["length"] == 4

    def test_strong_tag(self):
        text, entities = html_to_entities("<strong>bold</strong>")
        assert text == "bold"
        assert entities[0]["type"] == "bold"

    def test_italic_tag(self):
        text, entities = html_to_entities("<i>italic</i>")
        assert text == "italic"
        assert entities[0]["type"] == "italic"
        assert entities[0]["offset"] == 0
        assert entities[0]["length"] == 6

    def test_em_tag(self):
        text, entities = html_to_entities("<em>italic</em>")
        assert text == "italic"
        assert entities[0]["type"] == "italic"

    def test_code_tag(self):
        text, entities = html_to_entities("<code>x</code>")
        assert text == "x"
        assert entities[0]["type"] == "code"

    def test_pre_tag(self):
        text, entities = html_to_entities("<pre>block</pre>")
        assert text == "block"
        assert entities[0]["type"] == "pre"

    @pytest.mark.parametrize("tag", ["s", "strike", "del"])
    def test_strikethrough_tags(self, tag):
        text, entities = html_to_entities(f"<{tag}>strike</{tag}>")
        assert text == "strike"
        assert entities[0]["type"] == "strikethrough"

    @pytest.mark.parametrize("tag", ["u", "ins"])
    def test_underline_tags(self, tag):
        text, entities = html_to_entities(f"<{tag}>under</{tag}>")
        assert text == "under"
        assert entities[0]["type"] == "underline"

    def test_spoiler_tag(self):
        text, entities = html_to_entities("<tg-spoiler>secret</tg-spoiler>")
        assert text == "secret"
        assert entities[0]["type"] == "spoiler"

    def test_blockquote_tag(self):
        text, entities = html_to_entities("<blockquote>quote</blockquote>")
        assert text == "quote"
        assert entities[0]["type"] == "blockquote"

    def test_link_tag(self):
        text, entities = html_to_entities('<a href="https://example.com">click</a>')
        assert text == "click"
        assert entities[0]["type"] == "text_link"
        assert entities[0]["url"] == "https://example.com"
        assert entities[0]["offset"] == 0
        assert entities[0]["length"] == 5

    def test_link_no_href(self):
        # When href is absent, url="" is falsy so the key is not added to the entity
        text, entities = html_to_entities("<a>text</a>")
        assert text == "text"
        assert entities[0]["type"] == "text_link"
        assert entities[0].get("url", "") == ""

    def test_tg_emoji(self):
        text, entities = html_to_entities('<tg-emoji emoji-id="123">🎉</tg-emoji>')
        assert text == "🎉"
        assert entities[0]["type"] == "custom_emoji"
        assert entities[0]["custom_emoji_id"] == "123"
        # 🎉 U+1F389 is a surrogate pair → length 2
        assert entities[0]["length"] == 2

    def test_nested_tags(self):
        text, entities = html_to_entities("<b><i>bi</i></b>")
        assert text == "bi"
        assert len(entities) == 2
        types = {e["type"] for e in entities}
        assert types == {"bold", "italic"}
        for e in entities:
            assert e["offset"] == 0
            assert e["length"] == 2

    def test_adjacent_tags(self):
        text, entities = html_to_entities("<b>a</b><i>b</i>")
        assert text == "ab"
        assert len(entities) == 2
        bold = next(e for e in entities if e["type"] == "bold")
        italic = next(e for e in entities if e["type"] == "italic")
        assert bold["offset"] == 0
        assert bold["length"] == 1
        assert italic["offset"] == 1
        assert italic["length"] == 1

    def test_html_entity_amp(self):
        text, entities = html_to_entities("a&amp;b")
        assert text == "a&b"
        assert entities == []

    def test_html_entity_lt_gt(self):
        text, entities = html_to_entities("&lt;tag&gt;")
        assert text == "<tag>"
        assert entities == []

    def test_unclosed_angle_bracket(self):
        # "<" without a closing ">" should be treated as literal text
        text, entities = html_to_entities("hello < world")
        assert "<" in text
        assert entities == []

    def test_emoji_utf16_surrogates(self):
        # "🔥" is U+1F525 — 2 UTF-16 code units
        # "<b>🔥</b>" → text="🔥", entity offset=0, length=2
        text, entities = html_to_entities("<b>🔥</b>")
        assert text == "🔥"
        assert entities[0]["offset"] == 0
        assert entities[0]["length"] == 2

    def test_offset_after_emoji(self):
        # "🔥<b>x</b>" — "🔥" takes 2 UTF-16 code units, so <b>x</b> should start at offset 2
        text, entities = html_to_entities("🔥<b>x</b>")
        assert text == "🔥x"
        assert entities[0]["offset"] == 2
        assert entities[0]["length"] == 1

    def test_mixed_content(self):
        # Complex HTML: text before tag, tag, text after, HTML entity
        html = "Hello <b>world</b> &amp; <i>more</i>!"
        text, entities = html_to_entities(html)
        assert text == "Hello world & more!"
        assert len(entities) == 2
        bold = next(e for e in entities if e["type"] == "bold")
        italic = next(e for e in entities if e["type"] == "italic")
        # "Hello " = 6 chars/units
        assert bold["offset"] == 6
        assert bold["length"] == 5  # "world"
        # "Hello world & " = 14 chars/units
        assert italic["offset"] == 14
        assert italic["length"] == 4  # "more"


# ===========================================================================
# append_timestamp
# ===========================================================================


class TestAppendTimestamp:
    """Tests for append_timestamp()."""

    def test_appends_two_extra_entities(self):
        _, entities = append_timestamp("<b>hello</b>", 1234567890)
        # 1 from <b>, plus custom_emoji + date_time appended
        assert len(entities) == 3

    def test_timestamp_in_text(self):
        full_text, _ = append_timestamp("hello", 1234567890)
        assert full_text.endswith("1234567890")

    def test_text_starts_with_original(self):
        full_text, _ = append_timestamp("hello", 1000)
        assert full_text.startswith("hello")

    def test_custom_emoji_offset(self):
        # plain_text="hello" (5 UTF-16 units), then "\n\n" (2 units) before 🔄
        _, entities = append_timestamp("hello", 1000)
        emoji_entity = next(e for e in entities if e["type"] == "custom_emoji")
        # offset = _utf16_len("hello") + _utf16_len("\n\n") = 5 + 2 = 7
        assert emoji_entity["offset"] == 7
        assert emoji_entity["length"] == 2  # 🔄 is a surrogate pair

    def test_date_time_offset(self):
        # prefix = "\n\n🔄 Час останнього оновлення даних: "
        # _utf16_len(prefix) = 37
        _, entities = append_timestamp("hello", 1000)
        dt_entity = next(e for e in entities if e["type"] == "date_time")
        # offset = _utf16_len("hello") + _utf16_len(prefix) = 5 + 37 = 42
        assert dt_entity["offset"] == 42
        assert dt_entity["unix_time"] == 1000
        assert dt_entity["date_time_format"] == "r"

    def test_date_time_length(self):
        ts = 9876543210
        _, entities = append_timestamp("hi", ts)
        dt_entity = next(e for e in entities if e["type"] == "date_time")
        assert dt_entity["length"] == len(str(ts))

    def test_preserves_original_entities(self):
        _, entities = append_timestamp("<b>bold</b>", 1000)
        bold = next(e for e in entities if e["type"] == "bold")
        assert bold["offset"] == 0
        assert bold["length"] == 4

    def test_empty_html(self):
        full_text, entities = append_timestamp("", 42)
        assert full_text.endswith("42")
        # Should have exactly 2 entities (custom_emoji + date_time)
        assert len(entities) == 2


# ===========================================================================
# to_aiogram_entities
# ===========================================================================


class TestToAiogramEntities:
    """Tests for to_aiogram_entities()."""

    def test_empty_list(self):
        result = to_aiogram_entities([])
        assert result == []

    def test_basic_conversion(self):
        raw = [{"type": "bold", "offset": 0, "length": 4}]
        result = to_aiogram_entities(raw)
        assert len(result) == 1
        assert isinstance(result[0], MessageEntity)
        assert result[0].type == "bold"
        assert result[0].offset == 0
        assert result[0].length == 4

    def test_url_key_preserved(self):
        raw = [{"type": "text_link", "offset": 0, "length": 5, "url": "https://example.com"}]
        result = to_aiogram_entities(raw)
        assert result[0].url == "https://example.com"

    def test_custom_emoji_id_preserved(self):
        raw = [{"type": "custom_emoji", "offset": 0, "length": 2, "custom_emoji_id": "123456"}]
        result = to_aiogram_entities(raw)
        assert result[0].custom_emoji_id == "123456"

    def test_multiple_entities(self):
        raw = [
            {"type": "bold", "offset": 0, "length": 4},
            {"type": "italic", "offset": 5, "length": 3},
        ]
        result = to_aiogram_entities(raw)
        assert len(result) == 2
        assert all(isinstance(e, MessageEntity) for e in result)
        assert result[0].type == "bold"
        assert result[1].type == "italic"
        assert result[1].offset == 5

    def test_optional_keys_not_present_when_absent(self):
        raw = [{"type": "code", "offset": 0, "length": 3}]
        result = to_aiogram_entities(raw)
        assert result[0].url is None
        assert result[0].custom_emoji_id is None


# ===========================================================================
# bot/utils/branding.py
# ===========================================================================


class TestBuildChannelTitle:
    """Tests for build_channel_title()."""

    def test_normal_title(self):
        result = build_channel_title("My City")
        assert result == f"{CHANNEL_NAME_PREFIX}My City"

    def test_empty_title(self):
        result = build_channel_title("")
        assert result == CHANNEL_NAME_PREFIX

    def test_truncation(self):
        long_title = "A" * 200
        result = build_channel_title(long_title)
        assert len(result) <= _TITLE_MAX
        assert result.startswith(CHANNEL_NAME_PREFIX)

    def test_exact_max_length_not_exceeded(self):
        # Construct a title that results in exactly _TITLE_MAX chars
        max_user_part = "B" * (_TITLE_MAX - len(CHANNEL_NAME_PREFIX))
        result = build_channel_title(max_user_part)
        assert len(result) == _TITLE_MAX

    def test_prefix_always_present(self):
        result = build_channel_title("test")
        assert result.startswith(CHANNEL_NAME_PREFIX)


class TestBuildChannelDescription:
    """Tests for build_channel_description()."""

    def test_with_description(self):
        result = build_channel_description("My desc")
        assert result is not None
        assert "My desc" in result
        assert CHANNEL_DESCRIPTION_BASE in result

    def test_with_bot_username(self):
        result = build_channel_description("My desc", bot_username="mybot")
        assert result is not None
        assert "@mybot" in result

    def test_without_bot_username(self):
        result = build_channel_description("My desc")
        assert result is not None
        assert "@" not in result or CHANNEL_DESCRIPTION_BASE in result

    def test_none_input_returns_none(self):
        assert build_channel_description(None) is None

    def test_empty_string_input_returns_none(self):
        assert build_channel_description("") is None

    def test_truncation(self):
        long_desc = "X" * 300
        result = build_channel_description(long_desc)
        assert result is not None
        assert len(result) <= _DESC_MAX

    def test_newlines_separate_parts(self):
        result = build_channel_description("User text")
        assert result is not None
        assert "\n\n" in result


class TestGetChannelWelcomeMessage:
    """Tests for get_channel_welcome_message()."""

    def test_with_bot_username(self):
        msg = get_channel_welcome_message("1.1", bot_username="mybot")
        assert '<a href="https://t.me/mybot">Вольтика</a>' in msg

    def test_without_bot_username(self):
        msg = get_channel_welcome_message("1.1", bot_username=None)
        assert "Вольтика" in msg
        assert "<a href=" not in msg

    def test_with_known_region(self):
        # "kyiv" maps to "Київ" in REGIONS
        msg = get_channel_welcome_message("1.1", region="kyiv")
        assert "Київ" in msg
        assert "Регіон:" in msg

    def test_with_unknown_region(self):
        # Unknown region code is used as-is
        msg = get_channel_welcome_message("1.1", region="unknown-region")
        assert "unknown-region" in msg

    def test_without_region(self):
        msg = get_channel_welcome_message("2.1", region=None)
        assert "Черга: 2.1" in msg
        assert "Регіон:" not in msg

    def test_with_has_ip_true(self):
        msg = get_channel_welcome_message("1.1", has_ip=True)
        assert "⚡ Сповіщення про стан світла" in msg

    def test_with_has_ip_false(self):
        msg = get_channel_welcome_message("1.1", has_ip=False)
        assert "⚡ Сповіщення про стан світла" not in msg

    def test_queue_always_present(self):
        msg = get_channel_welcome_message("3.2")
        assert "3.2" in msg

    def test_contains_channel_description(self):
        msg = get_channel_welcome_message("1.1")
        assert "моніторингу світла" in msg


# ===========================================================================
# bot/utils/logger.py
# ===========================================================================


class TestGetLogger:
    """Tests for get_logger()."""

    def test_get_logger_returns_object(self):
        logger = get_logger("test.module")
        assert logger is not None

    def test_get_logger_name(self):
        # structlog bound loggers expose _logger or similar; verify the name
        # via the underlying stdlib logger
        _logger = get_logger("test.named")
        stdlib_logger = logging.getLogger("test.named")
        assert stdlib_logger.name == "test.named"

    def test_get_logger_different_names_independent(self):
        _logger_a = get_logger("module.a")
        _logger_b = get_logger("module.b")
        assert logging.getLogger("module.a") is not logging.getLogger("module.b")


class TestSetupLogging:
    """Tests for setup_logging()."""

    def setup_method(self):
        # Ensure bot.config is imported so it can be patched
        import bot.config  # noqa: F401

    def _make_mock_settings(self, environment: str) -> MagicMock:
        mock_settings = MagicMock()
        mock_settings.ENVIRONMENT = environment
        mock_settings.LOG_LEVEL = "INFO"
        return mock_settings

    def test_setup_logging_sets_root_level_to_info(self):
        with patch("bot.config.settings", self._make_mock_settings("development")):
            setup_logging()
        root = logging.getLogger()
        assert root.level == logging.INFO

    def test_setup_logging_mutes_aiogram(self):
        with patch("bot.config.settings", self._make_mock_settings("development")):
            setup_logging()
        assert logging.getLogger("aiogram").level == logging.WARNING

    def test_setup_logging_mutes_sqlalchemy(self):
        with patch("bot.config.settings", self._make_mock_settings("development")):
            setup_logging()
        assert logging.getLogger("sqlalchemy.engine").level == logging.WARNING

    def test_setup_logging_production_uses_json_renderer(self):
        with patch("bot.config.settings", self._make_mock_settings("production")):
            with patch("structlog.stdlib.ProcessorFormatter") as mock_pf:
                setup_logging()
                call_kwargs = mock_pf.call_args[1]
                renderer = call_kwargs.get("processor")

        assert isinstance(renderer, structlog.processors.JSONRenderer)

    def test_setup_logging_dev_uses_console_renderer(self):
        with patch("bot.config.settings", self._make_mock_settings("development")):
            with patch("structlog.stdlib.ProcessorFormatter") as mock_pf:
                setup_logging()
                call_kwargs = mock_pf.call_args[1]
                renderer = call_kwargs.get("processor")

        assert isinstance(renderer, structlog.dev.ConsoleRenderer)

    def test_setup_logging_adds_handler_to_root(self):
        with patch("bot.config.settings", self._make_mock_settings("development")):
            setup_logging()
        root = logging.getLogger()
        assert len(root.handlers) >= 1
        assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)
