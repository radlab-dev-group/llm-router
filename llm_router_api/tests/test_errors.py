"""
Unit tests for ``llm_router_api.core.errors``.

Covers the JSON error-dict helper and the ``sanitize_error_message``
redaction function (URL / IP / port / host removal, idempotency, and the
fallback text when everything is stripped).
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402

from llm_router_api.core import errors  # noqa: E402


class TestErrorAsDict:
    """``error_as_dict`` builds JSON-serialisable error payloads."""

    def test_code_only(self):
        assert errors.error_as_dict("E1") == {"error": "E1"}

    def test_code_and_message(self):
        expected = {"error": "E1", "message": "boom"}
        assert errors.error_as_dict("E1", "boom") == expected

    def test_explicit_none_message_omitted(self):
        assert errors.error_as_dict("E1", None) == {"error": "E1"}

    def test_required_params_constant(self):
        assert errors.ERROR_NO_REQUIRED_PARAMS == "No required parameters!"


class TestSanitizeErrorMessage:
    """``sanitize_error_message`` removes network-sensitive details."""

    def test_url_removed(self):
        assert (
            errors.sanitize_error_message(
                "reached https://api.example.com/v1/chat then failed"
            )
            == "reached then failed"
        )

    def test_host_and_port_params_removed(self):
        assert (
            errors.sanitize_error_message(
                "HTTPConnectionPool(host='10.0.1.50', port=8080): boom"
            )
            == "boom"
        )

    def test_bracket_ip_port_removed(self):
        assert (
            errors.sanitize_error_message("connection [10.0.1.50:8080] failed")
            == "connection failed"
        )

    def test_connection_to_ip_removed(self):
        assert (
            errors.sanitize_error_message("Connection to 10.0.1.50 timed out.")
            == "timed out"
        )

    def test_urllib3_object_reference_removed(self):
        assert (
            errors.sanitize_error_message(
                "bad <urllib3.connection object at 0x7f1234> end"
            )
            == "bad end"
        )

    def test_whole_removal_fallback_text(self):
        assert (
            errors.sanitize_error_message("https://api.example.com")
            == "A connection error occurred"
        )

    def test_safe_message_preserved(self):
        # Only whitespace is collapsed; the text itself is untouched.
        assert (
            errors.sanitize_error_message("a perfectly safe message")
            == "a perfectly safe message"
        )

    def test_whitespace_collapsed(self):
        assert (
            errors.sanitize_error_message("a   safe   message") == "a safe message"
        )

    def test_idempotent(self):
        raw = (
            "HTTPConnectionPool(host='10.0.1.50', port=8080): "
            "Max retries exceeded with url: https://api.example.com/v1/chat "
            "(Caused by NewConnectionError: "
            "'Connection to 10.0.1.50 timed out.' (connect timeout=1))"
        )
        once = errors.sanitize_error_message(raw)
        twice = errors.sanitize_error_message(once)
        assert once == twice

    @pytest.mark.parametrize(
        "leak",
        ["10.0.1.50", "8080", "https://api.example.com", "host="],
    )
    def test_sensitive_details_absent(self, leak):
        raw = (
            "HTTPConnectionPool(host='10.0.1.50', port=8080): "
            "Max retries exceeded with url: https://api.example.com/v1/chat "
            "(Caused by NewConnectionError: 'Connection to 10.0.1.50 timed out.')"
        )
        assert leak not in errors.sanitize_error_message(raw)
