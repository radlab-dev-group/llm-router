"""
Unit tests for ``llm_router_api.core.utils.StrategyHelpers``.

Pure-function helpers for decoding Redis values, normalising model names and
extracting hosts from provider dictionaries.  No external services required.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402

from llm_router_api.core.utils import StrategyHelpers  # noqa: E402


class TestDecodeRedis:
    """``decode_redis`` normalises Redis return values to ``str``/``None``."""

    def test_none_returns_none(self):
        assert StrategyHelpers.decode_redis(None) is None

    def test_bytes_returns_str(self):
        assert StrategyHelpers.decode_redis(b"hello") == "hello"

    def test_bytearray_returns_str(self):
        assert StrategyHelpers.decode_redis(bytearray(b"byte")) == "byte"

    def test_str_passes_through(self):
        assert StrategyHelpers.decode_redis("strval") == "strval"

    def test_int_converted_to_str(self):
        assert StrategyHelpers.decode_redis(123) == "123"

    def test_invalid_utf8_ignored(self):
        # 0xFF is not valid UTF-8; errors="ignore" must drop it silently.
        assert StrategyHelpers.decode_redis(b"ab\xffcd") == "abcd"


class TestNormalizeModelName:
    """``normalize_model_name`` strips prefixes and surrounding whitespace."""

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_falsy_input_returns_empty_string(self, value):
        assert StrategyHelpers.normalize_model_name(value) == ""

    def test_model_prefix_stripped(self):
        assert StrategyHelpers.normalize_model_name(" model:foo ") == "foo"

    def test_host_prefix_stripped(self):
        assert StrategyHelpers.normalize_model_name("host:bar") == "bar"

    def test_chained_prefixes_stripped(self):
        assert StrategyHelpers.normalize_model_name("model:host:x") == "x"

    def test_plain_name_untouched(self):
        assert StrategyHelpers.normalize_model_name("plain") == "plain"


class TestHostFromProvider:
    """``host_from_provider`` prefers ``api_host`` over ``host``."""

    def test_api_host_preferred(self):
        assert StrategyHelpers.host_from_provider({"api_host": "a"}) == "a"

    def test_fallback_to_host(self):
        assert StrategyHelpers.host_from_provider({"host": "b"}) == "b"

    def test_empty_api_host_falls_back_to_host(self):
        provider = {"api_host": "", "host": "b"}
        assert StrategyHelpers.host_from_provider(provider) == "b"

    def test_no_host_keys_returns_none(self):
        assert StrategyHelpers.host_from_provider({}) is None

    def test_both_keys_api_host_wins(self):
        provider = {"api_host": "a", "host": "b"}
        assert StrategyHelpers.host_from_provider(provider) == "a"
