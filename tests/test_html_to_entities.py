"""Tests for bot/utils/html_to_entities.py."""
from __future__ import annotations

from bot.utils.html_to_entities import append_timestamp, html_to_entities, to_aiogram_entities


class TestHtmlToEntities:
    """Tests for html_to_entities()."""

    def test_plain_text_unchanged(self):
        text, entities = html_to_entities("Hello world")
        assert text == "Hello world"
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

    def test_strong_tag_same_as_bold(self):
        text, entities = html_to_entities("<strong>text</strong>")
        assert text == "text"
        assert entities[0]["type"] == "bold"

    def test_italic_tag(self):
        text, entities = html_to_entities("<i>italic</i>")
        assert text == "italic"
        assert entities[0]["type"] == "italic"

    def test_em_tag_same_as_italic(self):
        text, entities = html_to_entities("<em>em</em>")
        assert entities[0]["type"] == "italic"

    def test_code_tag(self):
        text, entities = html_to_entities("<code>print()</code>")
        assert text == "print()"
        assert entities[0]["type"] == "code"

    def test_strikethrough_tag(self):
        text, entities = html_to_entities("<s>strike</s>")
        assert text == "strike"
        assert entities[0]["type"] == "strikethrough"

    def test_underline_tag(self):
        text, entities = html_to_entities("<u>under</u>")
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

    def test_link_with_single_quotes(self):
        text, entities = html_to_entities("<a href='https://t.me/bot'>bot</a>")
        assert entities[0]["url"] == "https://t.me/bot"

    def test_tg_emoji_tag(self):
        text, entities = html_to_entities('<tg-emoji emoji-id="12345">🔥</tg-emoji>')
        assert entities[0]["type"] == "custom_emoji"
        assert entities[0]["custom_emoji_id"] == "12345"

    def test_html_entity_amp(self):
        text, entities = html_to_entities("a &amp; b")
        assert text == "a & b"
        assert entities == []

    def test_html_entity_lt(self):
        text, entities = html_to_entities("&lt;tag&gt;")
        assert text == "<tag>"

    def test_mixed_text_and_bold(self):
        text, entities = html_to_entities("Hello <b>world</b>!")
        assert text == "Hello world!"
        assert entities[0]["offset"] == 6
        assert entities[0]["length"] == 5

    def test_offset_is_utf16_units(self):
        """Emoji = 2 UTF-16 code units; offset of 'b' text must account for that."""
        text, entities = html_to_entities("😀<b>text</b>")
        assert text == "😀text"
        # 😀 is U+1F600, encoded as surrogate pair → 2 UTF-16 units
        assert entities[0]["offset"] == 2

    def test_nested_tags(self):
        text, entities = html_to_entities("<b><i>bold italic</i></b>")
        assert text == "bold italic"
        types = {e["type"] for e in entities}
        assert "bold" in types
        assert "italic" in types

    def test_unclosed_angle_bracket_treated_as_text(self):
        """A '<' with no matching '>' is treated as a literal character."""
        text, entities = html_to_entities("a < b")
        assert "<" in text
        assert entities == []

    def test_unknown_tag_ignored(self):
        text, entities = html_to_entities("<span>text</span>")
        assert text == "text"
        assert entities == []

    def test_multiple_entities(self):
        text, entities = html_to_entities("<b>bold</b> and <i>italic</i>")
        assert text == "bold and italic"
        assert len(entities) == 2


class TestAppendTimestamp:
    def test_returns_tuple(self):
        result = append_timestamp("<b>hello</b>", 1700000000)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_plain_text_contains_timestamp(self):
        text, _ = append_timestamp("Hello", 1700000000)
        assert "1700000000" in text

    def test_entities_include_custom_emoji(self):
        _, entities = append_timestamp("Hello", 1700000000)
        types = [e["type"] for e in entities]
        assert "custom_emoji" in types

    def test_entities_include_date_time(self):
        _, entities = append_timestamp("Hello", 1700000000)
        types = [e["type"] for e in entities]
        assert "date_time" in types

    def test_date_time_entity_has_unix_time(self):
        _, entities = append_timestamp("Hello", 1700000000)
        dt_entity = next(e for e in entities if e["type"] == "date_time")
        assert dt_entity["unix_time"] == 1700000000

    def test_existing_entities_preserved(self):
        _, entities = append_timestamp("<b>bold</b>", 1700000000)
        types = [e["type"] for e in entities]
        assert "bold" in types


class TestToAiogramEntities:
    def test_empty_list(self):
        result = to_aiogram_entities([])
        assert result == []

    def test_converts_bold_entity(self):
        from aiogram.types import MessageEntity
        raw = [{"type": "bold", "offset": 0, "length": 5}]
        result = to_aiogram_entities(raw)
        assert len(result) == 1
        assert isinstance(result[0], MessageEntity)
        assert result[0].type == "bold"

    def test_converts_link_entity(self):
        raw = [{"type": "text_link", "offset": 0, "length": 4, "url": "https://example.com"}]
        result = to_aiogram_entities(raw)
        assert result[0].url == "https://example.com"

    def test_converts_custom_emoji(self):
        raw = [{"type": "custom_emoji", "offset": 0, "length": 2, "custom_emoji_id": "123"}]
        result = to_aiogram_entities(raw)
        assert result[0].custom_emoji_id == "123"
