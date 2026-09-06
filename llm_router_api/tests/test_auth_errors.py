"""
Unit tests for ``llm_router_api.core.auth.errors``.

Covers the frozen :class:`AuthResult` dataclass, the reason→message
mapping and the OpenAI-compatible error response builders.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import dataclasses  # noqa: E402

import pytest  # noqa: E402

from llm_router_api.core.auth.errors import (  # noqa: E402
    AuthResult,
    auth_429_response,
    auth_error_message,
    auth_error_response,
)


class TestAuthResult:
    def test_fields(self):
        result = AuthResult(
            allowed=True,
            reason="ok",
            status_code=200,
            key_id="key-1",
        )
        assert result.allowed is True
        assert result.reason == "ok"
        assert result.status_code == 200
        assert result.key_id == "key-1"

    def test_headers_default_to_empty_dict(self):
        result = AuthResult(allowed=False, reason="x", status_code=401)
        assert result.headers == {}

    def test_headers_can_be_set(self):
        result = AuthResult(
            allowed=False,
            reason="rate_limit",
            status_code=429,
            headers={"Retry-After": "30"},
        )
        assert result.headers == {"Retry-After": "30"}

    def test_frozen(self):
        result = AuthResult(allowed=True, reason="ok", status_code=200)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.allowed = False  # type: ignore[misc]

    def test_key_id_defaults_to_none(self):
        result = AuthResult(allowed=False, reason="x", status_code=403)
        assert result.key_id is None


class TestAuthErrorMessage:
    def test_known_reasons(self):
        assert "API key" in auth_error_message("missing_key")
        assert "not found" in auth_error_message("invalid_key")
        assert "deactivated" in auth_error_message("key_inactive")
        assert "expired" in auth_error_message("key_expired")
        assert "rotated" in auth_error_message("key_rotated")
        assert "Rate limit" in auth_error_message("rate_limit")
        assert "budget" in auth_error_message("budget_exceeded")

    def test_unknown_reason_falls_back(self):
        assert auth_error_message("something_new") == (
            "Authentication failed: something_new"
        )


class TestAuthErrorResponse:
    def test_shape(self):
        response = auth_error_response("invalid_key", 401)
        assert response["error"]["type"] == "authentication_error"
        assert response["error"]["param"] is None
        assert response["error"]["code"] == 401
        assert response["error"]["message"] == auth_error_message("invalid_key")

    def test_unknown_reason_code_preserved(self):
        response = auth_error_response("weird_reason", 403)
        assert response["error"]["code"] == 403
        assert "weird_reason" in response["error"]["message"]


class TestAuth429Response:
    def test_shape(self):
        response = auth_429_response(30)
        assert response["error"]["type"] == "rate_limit_error"
        assert response["error"]["code"] == 429
        assert response["error"]["retry_after"] == 30
        assert response["error"]["param"] is None

    def test_retry_after_int_coercion(self):
        assert auth_429_response("45")["error"]["retry_after"] == 45
