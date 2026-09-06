"""
Unit tests for the trivial built‑in endpoints ``Health`` and ``Ping``
(``llm_router_api.endpoints.builtin.builtin_health`` /
``builtin_ping``).

Both endpoints are parameterless ``GET`` probes; the tests verify the
response envelope produced by ``prepare_payload`` and the registration
wiring (route, method, api types, prefix opt‑out, guardrail exemption).
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from llm_router_api.endpoints.builtin.builtin_health import (  # noqa: E402
    Health,
)
from llm_router_api.endpoints.builtin.builtin_ping import Ping  # noqa: E402


class TestHealth:
    def test_prepare_payload_body(self):
        ep = Health()
        out = ep.prepare_payload(None)
        assert out["status"] is True
        assert out["body"] == "healthy"
        assert isinstance(out["response_time"], float)

    def test_params_are_ignored(self):
        ep = Health()
        out = ep.prepare_payload({"junk": 1, "model": "m"})
        assert out["status"] is True
        assert out["body"] == "healthy"

    def test_response_envelope_is_copied(self):
        ep = Health()
        base = Health.return_response_ok("healthy")
        out = ep.prepare_payload(None)
        assert (out["status"], out["body"]) == (base["status"], base["body"])
        assert set(out) == set(base) | {"response_time"}

    def test_registration(self):
        ep = Health()
        assert ep.name == "health"
        assert ep.method == "GET"
        assert ep._ep_types_str == ["builtin"]
        assert ep._dont_add_api_prefix is True
        assert ep.direct_return is True

    def test_guardrail_and_masking_exemption(self):
        ep = Health()
        assert ep.EP_DONT_NEED_GUARDRAIL_AND_MASKING is True
        assert ep.REQUIRED_ARGS == []
        assert ep.OPTIONAL_ARGS == []
        assert ep.SYSTEM_PROMPT_NAME is None

    def test_custom_ep_name_respected(self):
        ep = Health(ep_name="liveness")
        assert ep.name == "liveness"


class TestPing:
    def test_prepare_payload_body(self):
        ep = Ping()
        out = ep.prepare_payload(None)
        assert out["status"] is True
        assert out["body"] == "pong"
        assert isinstance(out["response_time"], float)

    def test_params_are_ignored(self):
        ep = Ping()
        out = ep.prepare_payload({"q": "x"})
        assert out["body"] == "pong"

    def test_registration(self):
        ep = Ping()
        assert ep.name == "ping"
        assert ep.method == "GET"
        assert ep._ep_types_str == ["builtin"]
        assert ep._dont_add_api_prefix is False
        assert ep.direct_return is True

    def test_guardrail_and_masking_exemption(self):
        ep = Ping()
        assert ep.EP_DONT_NEED_GUARDRAIL_AND_MASKING is True
        assert ep.REQUIRED_ARGS == []
        assert ep.OPTIONAL_ARGS == []
        assert ep.SYSTEM_PROMPT_NAME is None
