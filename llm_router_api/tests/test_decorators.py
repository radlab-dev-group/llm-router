"""
Unit tests for ``llm_router_api.core.decorators.EP``.

Covers the ``require_params`` and ``response_time`` endpoint decorators.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402

from llm_router_api.core.decorators import EP  # noqa: E402


class _Endpoint:
    """Minimal stand-in for an endpoint class instance."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.checked: dict = {}

    def _check_required_params(self, params: dict) -> None:
        self.checked = params
        if self.fail:
            raise ValueError("missing required arg 'prompt'")


class TestRequireParams:
    def test_params_none_treated_as_empty_dict(self):
        endpoint = _Endpoint()

        @EP.require_params
        def run(self, params=None):
            return {"ok": True}

        result = run(endpoint, None)
        assert result == {"ok": True}
        assert endpoint.checked == {}

    def test_params_forwarded_to_check_and_func(self):
        endpoint = _Endpoint()
        payload = {"prompt": "hi"}

        @EP.require_params
        def run(self, params=None):
            return params

        assert run(endpoint, payload) is payload
        assert endpoint.checked is payload

    def test_value_error_propagates_and_func_not_called(self):
        endpoint = _Endpoint(fail=True)
        called = []

        @EP.require_params
        def run(self, params=None):
            called.append(1)

        with pytest.raises(ValueError, match="prompt"):
            run(endpoint, {})
        assert called == []


class TestResponseTime:
    def test_dict_result_gets_response_time(self):
        endpoint = _Endpoint()

        @EP.response_time
        def run(self, params=None):
            return {"status": True}

        result = run(endpoint, {})
        assert "response_time" in result
        assert result["response_time"] >= 0
        assert result["status"] is True

    def test_original_dict_not_mutated(self):
        endpoint = _Endpoint()
        payload = {"status": True}

        @EP.response_time
        def run(self, params=None):
            return payload

        result = run(endpoint, {})
        assert "response_time" in result
        assert "response_time" not in payload

    def test_non_dict_result_unchanged(self):
        endpoint = _Endpoint()

        @EP.response_time
        def run(self, params=None):
            return "plain-string"

        assert run(endpoint, {}) == "plain-string"
