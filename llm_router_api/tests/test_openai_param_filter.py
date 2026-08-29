"""
Tests for ``_filter_params_to_acceptable`` (OpenAI provider whitelist).

Regression test: the whitelist previously omitted standard OpenAI sampling
parameters (``temperature``, ``top_p``, ``max_tokens``, ...), so they were
*silently dropped* from payloads forwarded to OpenAI-compatible providers —
changing the semantics of the request in a transparent proxy.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest

from llm_router_api.core.api_types.openai import OPENAI_ACCEPTABLE_PARAMS
from llm_router_api.endpoints.endpoint_i import EndpointWithHttpRequestI

# Parameters that must survive the filter for openai-typed providers.
MUST_PASSTHROUGH = [
    "model",
    "messages",
    "stream",
    "temperature",
    "top_p",
    "max_tokens",
    "n",
    "stop",
    "presence_penalty",
    "frequency_penalty",
    "response_format",
    "seed",
    "logprobs",
    "top_logprobs",
    "logit_bias",
    "user",
    "tools",
    "tool_choice",
]


class TestOpenaiParamWhitelist:
    """Whitelist completeness and filter behavior."""

    def test_sampling_params_are_whitelisted(self):
        for param in MUST_PASSTHROUGH:
            assert param in OPENAI_ACCEPTABLE_PARAMS, (
                f"parameter '{param}' missing from OPENAI_ACCEPTABLE_PARAMS — "
                "it would be silently dropped from openai-typed payloads"
            )

    def test_filter_keeps_sampling_params(self):
        params = {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
            "temperature": 0.2,
            "top_p": 0.9,
            "max_tokens": 512,
            "n": 1,
            "stop": ["\n"],
            "presence_penalty": 0.1,
            "frequency_penalty": 0.0,
            "response_format": {"type": "json_object"},
            "seed": 42,
            "logprobs": True,
            "top_logprobs": 5,
            "logit_bias": {"50256": -100},
            "user": "tester",
            "internal_debug_flag": True,  # not in the whitelist — must drop
        }

        filtered = EndpointWithHttpRequestI._filter_params_to_acceptable(
            api_type="openai", params=params
        )

        for key in MUST_PASSTHROUGH:
            if key in params:
                assert filtered.get(key) == params[key], f"'{key}' lost or altered"
        assert "internal_debug_flag" not in filtered

    def test_filter_does_not_mutate_input(self):
        params = {"model": "m", "temperature": 0.5, "unknown": 1}
        snapshot = dict(params)
        EndpointWithHttpRequestI._filter_params_to_acceptable(
            api_type="openai", params=params
        )
        assert params == snapshot

    def test_unsupported_api_type_raises(self):
        with pytest.raises(ValueError):
            EndpointWithHttpRequestI._filter_params_to_acceptable(
                api_type="nope", params={"model": "m"}
            )
