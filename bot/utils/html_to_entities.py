"""Convert Telegram HTML to plain text + MessageEntity array.

Supports: b/strong, i/em, code, pre, a, s/strike/del, u/ins, tg-spoiler, blockquote, tg-emoji.
"""
from __future__ import annotations

import re
from html import unescape

from aiogram.types import MessageEntity

TAG_MAP = {
    "b": "bold", "strong": "bold",
    "i": "italic", "em": "italic",
    "code": "code", "pre": "pre",
    "s": "strikethrough", "strike": "strikethrough", "del": "strikethrough",
    "u": "underline", "ins": "underline",
    "tg-spoiler": "spoiler",
    "blockquote": "blockquote",
}


def _utf16_len(s: str) -> int:
    """Return the number of UTF-16 code units for string s."""
    return len(s.encode("utf-16-le")) // 2


def html_to_entities(html: str) -> tuple[str, list[dict]]:
    entities: list[dict] = []
    # Accumulate plain-text fragments; join once at the end to avoid O(n²)
    # string copies that occur with ``text += char`` in a per-character loop.
    # We also maintain a running UTF-16 code-unit counter so that tag offsets
    # can be recorded without re-scanning already-processed text.
    text_parts: list[str] = []
    utf16_pos: int = 0   # running count of UTF-16 code units emitted so far
    i = 0
    stack: list[dict] = []

    def _append(fragment: str) -> None:
        nonlocal utf16_pos
        text_parts.append(fragment)
        utf16_pos += _utf16_len(fragment)

    while i < len(html):
        if html[i] == "<":
            close_tag = html.find(">", i)
            if close_tag == -1:
                _append(html[i])
                i += 1
                continue

            tag_content = html[i + 1 : close_tag]

            if tag_content.startswith("/"):
                tag_name = tag_content[1:].strip().lower().split()[0]
                for s in range(len(stack) - 1, -1, -1):
                    if stack[s]["tag"] == tag_name:
                        entry = stack[s]
                        entity: dict = {
                            "type": entry["entity_type"],
                            "offset": entry["offset"],
                            "length": utf16_pos - entry["offset"],
                        }
                        if entry.get("url"):
                            entity["url"] = entry["url"]
                        if entry.get("custom_emoji_id"):
                            entity["custom_emoji_id"] = entry["custom_emoji_id"]
                        entities.append(entity)
                        stack.pop(s)
                        break
            else:
                space_idx = tag_content.find(" ")
                tag_name = (tag_content if space_idx == -1 else tag_content[:space_idx]).strip().lower()

                if tag_name == "a":
                    href_match = re.search(r'href\s*=\s*["\']([^"\']*)["\']', tag_content, re.IGNORECASE)
                    url = href_match.group(1) if href_match else ""
                    stack.append({"tag": "a", "entity_type": "text_link", "offset": utf16_pos, "url": url})
                elif tag_name == "tg-emoji":
                    emoji_match = re.search(r'emoji-id\s*=\s*["\']([^"\']*)["\']', tag_content, re.IGNORECASE)
                    eid = emoji_match.group(1) if emoji_match else ""
                    stack.append({"tag": "tg-emoji", "entity_type": "custom_emoji", "offset": utf16_pos, "custom_emoji_id": eid})
                elif tag_name in TAG_MAP:
                    stack.append({"tag": tag_name, "entity_type": TAG_MAP[tag_name], "offset": utf16_pos})

            i = close_tag + 1
        elif html[i] == "&":
            semi_idx = html.find(";", i)
            if semi_idx != -1 and semi_idx - i < 8:
                html_entity = html[i : semi_idx + 1]
                _append(unescape(html_entity))
                i = semi_idx + 1
            else:
                _append(html[i])
                i += 1
        else:
            _append(html[i])
            i += 1

    return "".join(text_parts), entities


def append_timestamp(html_message: str, check_time_unix: int) -> tuple[str, list[dict]]:
    """Append a live date_time entity (Bot API 9.5) to an HTML message.

    Returns (plain_text, entities) — use with entities= parameter, NOT parse_mode.
    """
    plain_text, entities = html_to_entities(html_message)

    # Use 🔄 as placeholder in text, then overlay with animated custom emoji
    prefix = "\n\n🔄 Оновлено: "
    timestamp_str = str(check_time_unix)
    full_text = plain_text + prefix + timestamp_str

    # UTF-16 offset of plain_text end
    plain_utf16 = _utf16_len(plain_text)

    # "\n\n" is 2 UTF-16 code units; 🔄 is U+1F504 (surrogate pair → 2 UTF-16 code units)
    emoji_offset = plain_utf16 + _utf16_len("\n\n")  # offset of 🔄 in full_text (UTF-16)
    emoji_utf16_len = _utf16_len("🔄")  # 2

    # Animated refresh emoji overlay
    entities.append({
        "type": "custom_emoji",
        "offset": emoji_offset,
        "length": emoji_utf16_len,
        "custom_emoji_id": "5017470156276761427",
    })

    # UTF-16 length of the full prefix "\n\n🔄 Оновлено: "
    prefix_utf16 = _utf16_len(prefix)

    # Live relative timestamp (e.g. "3 секунди тому")
    entities.append({
        "type": "date_time",
        "offset": plain_utf16 + prefix_utf16,
        "length": _utf16_len(timestamp_str),
        "unix_time": check_time_unix,
        "date_time_format": "r",
    })

    return full_text, entities


def to_aiogram_entities(raw_entities: list[dict]) -> list[MessageEntity]:
    """Convert raw entity dicts (from html_to_entities/append_timestamp) to aiogram MessageEntity objects."""
    result = []
    for e in raw_entities:
        params = {"type": e["type"], "offset": e["offset"], "length": e["length"]}
        for key in ("url", "custom_emoji_id", "unix_time", "date_time_format"):
            if key in e:
                params[key] = e[key]
        result.append(MessageEntity(**params))
    return result
