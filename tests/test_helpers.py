"""Tests for bot/utils/helpers.py."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramRetryAfter

from bot.utils.helpers import is_valid_ip_or_domain, retry_bot_call, safe_parse_callback_int

# ─── is_valid_ip_or_domain ────────────────────────────────────────────────


class TestIsValidIpOrDomain:
    # --- Valid IPv4 ---

    def test_valid_ipv4_basic(self):
        result = is_valid_ip_or_domain("192.168.1.1")
        assert result["valid"] is True
        assert result["type"] == "ip"
        assert result["host"] == "192.168.1.1"
        assert result["port"] is None

    def test_valid_ipv4_with_port(self):
        result = is_valid_ip_or_domain("192.168.1.1:8080")
        assert result["valid"] is True
        assert result["type"] == "ip"
        assert result["host"] == "192.168.1.1"
        assert result["port"] == 8080

    def test_invalid_ipv4_all_zeros(self):
        # 0.0.0.0 is the "unspecified address" — not a valid router IP and
        # falls in a blocked network range (SSRF protection).
        result = is_valid_ip_or_domain("0.0.0.0")
        assert result["valid"] is False

    def test_invalid_ipv4_broadcast(self):
        # 255.255.255.255 is the broadcast address — rejected for SSRF safety.
        result = is_valid_ip_or_domain("255.255.255.255")
        assert result["valid"] is False

    def test_invalid_ipv4_loopback(self):
        # 127.0.0.1 loopback must be rejected (SSRF risk).
        result = is_valid_ip_or_domain("127.0.0.1")
        assert result["valid"] is False

    def test_invalid_ipv4_link_local_metadata(self):
        # 169.254.169.254 is the cloud metadata endpoint — must be rejected.
        result = is_valid_ip_or_domain("169.254.169.254")
        assert result["valid"] is False

    def test_valid_ipv4_port_min(self):
        result = is_valid_ip_or_domain("10.0.0.1:1")
        assert result["valid"] is True
        assert result["port"] == 1

    def test_valid_ipv4_port_max(self):
        result = is_valid_ip_or_domain("10.0.0.1:65535")
        assert result["valid"] is True
        assert result["port"] == 65535

    # --- Invalid IPv4 ---

    def test_invalid_ipv4_octet_too_large(self):
        result = is_valid_ip_or_domain("256.1.1.1")
        assert result["valid"] is False

    def test_invalid_ipv4_negative_octet(self):
        # Negative numbers don't match the digit regex, treated as invalid domain
        result = is_valid_ip_or_domain("-1.0.0.1")
        assert result["valid"] is False

    def test_invalid_port_too_large(self):
        result = is_valid_ip_or_domain("192.168.1.1:65536")
        assert result["valid"] is False
        assert "Порт" in result["error"]

    def test_invalid_port_zero(self):
        result = is_valid_ip_or_domain("192.168.1.1:0")
        assert result["valid"] is False

    # --- Valid domains ---

    def test_valid_domain_simple(self):
        result = is_valid_ip_or_domain("router.example.com")
        assert result["valid"] is True
        assert result["type"] == "domain"
        assert result["host"] == "router.example.com"
        assert result["port"] is None

    def test_valid_domain_with_port(self):
        result = is_valid_ip_or_domain("router.example.com:8080")
        assert result["valid"] is True
        assert result["type"] == "domain"
        assert result["port"] == 8080

    def test_valid_domain_single_label_with_tld(self):
        result = is_valid_ip_or_domain("myrouter.local")
        assert result["valid"] is True
        assert result["type"] == "domain"

    def test_valid_domain_hyphenated(self):
        result = is_valid_ip_or_domain("my-router.home.local")
        assert result["valid"] is True
        assert result["type"] == "domain"

    def test_valid_domain_mixed_case(self):
        result = is_valid_ip_or_domain("Router.Example.COM")
        assert result["valid"] is True
        assert result["type"] == "domain"

    # --- Invalid inputs ---

    def test_invalid_whitespace_in_address(self):
        # Only internal spaces (after strip) trigger the error
        result = is_valid_ip_or_domain("192.168 .1.1")
        assert result["valid"] is False
        assert "пробіл" in result["error"]

    def test_invalid_internal_whitespace_dot_space(self):
        result = is_valid_ip_or_domain("192.168. 1.1")
        assert result["valid"] is False

    def test_invalid_empty_string(self):
        result = is_valid_ip_or_domain("")
        assert result["valid"] is False

    def test_invalid_only_digits_no_dots(self):
        result = is_valid_ip_or_domain("12345")
        assert result["valid"] is False

    def test_invalid_domain_hyphen_at_start(self):
        result = is_valid_ip_or_domain("-bad.example.com")
        assert result["valid"] is False

    def test_invalid_domain_hyphen_at_end_label(self):
        result = is_valid_ip_or_domain("bad-.example.com")
        assert result["valid"] is False

    # --- Edge cases ---

    def test_strips_leading_whitespace(self):
        # address.strip() is called, so leading/trailing spaces alone are fine
        result = is_valid_ip_or_domain("  192.168.1.1  ")
        # strip removes outer spaces; no internal space remains
        assert result["valid"] is True

    def test_port_not_digit_treated_as_no_port(self):
        # "router.example.com:abc" — "abc".isdigit() is False, so no port extracted
        result = is_valid_ip_or_domain("router.example.com:abc")
        # host remains "router.example.com:abc", which won't match IP, but may match domain regex
        # The full string with ":abc" won't match domain regex either → invalid
        assert result["valid"] is False

    def test_address_returned_in_result(self):
        addr = "192.168.1.1:9000"
        result = is_valid_ip_or_domain(addr)
        assert result["address"] == addr


# ─── retry_bot_call ───────────────────────────────────────────────────────


class TestRetryBotCall:
    async def test_succeeds_on_first_try(self):
        call_count = 0

        async def coro():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_bot_call(lambda: coro())
        assert result == "ok"
        assert call_count == 1

    async def test_retries_on_telegram_retry_after(self):
        call_count = 0

        async def coro():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TelegramRetryAfter(method=MagicMock(), message="Too Many Requests: retry after 1", retry_after=0)
            return "ok"

        with patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
            result = await retry_bot_call(lambda: coro(), max_retries=1)

        assert result == "ok"
        assert call_count == 2
        mock_sleep.assert_called_once()

    async def test_raises_after_max_retries_exhausted(self):
        async def always_fail():
            raise TelegramRetryAfter(method=MagicMock(), message="Too Many Requests: retry after 1", retry_after=0)

        with patch("asyncio.sleep", new=AsyncMock()):
            with pytest.raises(TelegramRetryAfter):
                await retry_bot_call(lambda: always_fail(), max_retries=2)

    async def test_does_not_retry_on_other_exceptions(self):
        call_count = 0

        async def coro():
            nonlocal call_count
            call_count += 1
            raise ValueError("not a rate limit error")

        with pytest.raises(ValueError):
            await retry_bot_call(lambda: coro(), max_retries=3)

        assert call_count == 1

    async def test_returns_value_from_factory(self):
        async def coro():
            return {"data": 42}

        result = await retry_bot_call(lambda: coro())
        assert result == {"data": 42}


# ─── safe_parse_callback_int ─────────────────────────────────────────────


class TestSafeParseCallbackInt:
    def test_valid_int(self):
        assert safe_parse_callback_int("notif_time_15", "notif_time_") == 15

    def test_valid_zero(self):
        assert safe_parse_callback_int("prefix_0", "prefix_") == 0

    def test_valid_negative(self):
        assert safe_parse_callback_int("prefix_-5", "prefix_") == -5

    def test_invalid_not_a_number(self):
        assert safe_parse_callback_int("notif_time_abc", "notif_time_") is None

    def test_invalid_empty_remainder(self):
        assert safe_parse_callback_int("notif_time_", "notif_time_") is None

    def test_wrong_prefix(self):
        assert safe_parse_callback_int("other_data_15", "notif_time_") is None

    def test_empty_data(self):
        assert safe_parse_callback_int("", "notif_time_") is None

    def test_float_value(self):
        assert safe_parse_callback_int("prefix_3.14", "prefix_") is None

    def test_none_data(self):
        assert safe_parse_callback_int(None, "prefix_") is None


# ─── retry_bot_call: unreachable branch ──────────────────────────────────


class TestRetryBotCallUnreachable:
    async def test_raises_runtime_error_when_loop_never_executes(self):
        """Line 49: range(max_retries+1) is empty when max_retries=-1."""
        async def coro():
            return "ok"

        with pytest.raises(RuntimeError, match="unreachable"):
            await retry_bot_call(lambda: coro(), max_retries=-1)


# ─── is_valid_ip_or_domain: ValueError branch ─────────────────────────────


class TestIsValidIpValueErrorBranch:
    def test_ipv4address_valueerror_falls_through_to_valid(self):
        """Lines 91-92: if IPv4Address raises ValueError, address is still valid."""
        with patch("bot.utils.helpers.ipaddress.IPv4Address", side_effect=ValueError("mocked")):
            result = is_valid_ip_or_domain("192.168.1.1")
        assert result["valid"] is True
        assert result["type"] == "ip"
