"""
Unit tests for :class:`AnthropicChatHandler` in
``llm_router_api.endpoints.builtin.anthropic``.

Covered without network/Flask:

* ``prepare_response_function`` – Ollama, OpenAI and passthrough branches;
* ``prepare_payload`` – the inherited pass‑through behaviour;
* registration defaults (route, method, prefix, api types).
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from llm_router_api.endpoints.builtin import (  # noqa: E402
    anthropic as anthropic_ep,
)


class _FakeResponse:
    """Minimal stand‑in for a ``requests.Response`` exposing ``.json()``."""

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


_OLLAMA_CHAT = {
    "model": "m1",
    "message": {"role": "assistant", "content": "Cześć!"},
    "done": True,
    "prompt_eval_count": 3,
    "eval_count": 4,
}

_OPENAI_CHAT = {
    "id": "c1",
    "model": "gpt",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "hi"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
}


class TestAnthropicChatHandlerConverters:
    def test_ollama_response_converted_to_anthropic(self):
        out = anthropic_ep.AnthropicChatHandler.prepare_response_function(
            _FakeResponse(_OLLAMA_CHAT)
        )
        assert out["type"] == "message"
        assert out["role"] == "assistant"
        assert out["content"] == [{"type": "text", "text": "Cześć!"}]
        assert out["model"] == "m1"
        assert out["stop_reason"] == "end_turn"
        assert out["usage"] == {"input_tokens": 3, "output_tokens": 4}
        assert out["id"].startswith("ollama-")

    def test_openai_response_converted_to_anthropic(self):
        out = anthropic_ep.AnthropicChatHandler.prepare_response_function(
            _FakeResponse(_OPENAI_CHAT)
        )
        assert out["type"] == "message"
        assert out["id"] == "c1"
        assert out["content"] == [{"type": "text", "text": "hi"}]
        assert out["stop_reason"] == "stop"
        assert out["usage"] == {"input_tokens": 1, "output_tokens": 2}

    def test_ollama_marker_wins_over_openai(self):
        body = dict(_OPENAI_CHAT, message=_OLLAMA_CHAT["message"], done=True)
        out = anthropic_ep.AnthropicChatHandler.prepare_response_function(
            _FakeResponse(body)
        )
        # the "message" branch (Ollama converter) is taken, not OpenAI
        assert out["content"] == [{"type": "text", "text": "Cześć!"}]
        assert out["stop_reason"] == "end_turn"
        assert out["usage"] == {"input_tokens": 0, "output_tokens": 0}

    def test_unknown_shape_passes_through(self):
        body = {"foo": "bar"}
        out = anthropic_ep.AnthropicChatHandler.prepare_response_function(
            _FakeResponse(body)
        )
        assert out is body

    def test_empty_ollama_content_stays_empty(self):
        body = {"model": "m", "message": {"role": "assistant", "content": ""}}
        out = anthropic_ep.AnthropicChatHandler.prepare_response_function(
            _FakeResponse(body)
        )
        assert out["content"] == []
        assert out["stop_reason"] is None


class TestAnthropicChatHandlerPayload:
    def test_prepare_payload_passthrough(self):
        ep = anthropic_ep.AnthropicChatHandler()
        params = {
            "model": "m",
            "messages": [{"role": "user", "content": "x"}],
            "max_tokens": 100,
        }
        out = ep.prepare_payload(params)
        assert out["model"] == "m"
        assert out["max_tokens"] == 100
        assert "response_time" in out
        assert "response_time" not in params

    def test_prepare_payload_none(self):
        ep = anthropic_ep.AnthropicChatHandler()
        out = ep.prepare_payload(None)
        assert out == {"response_time": out["response_time"]}

    def test_prepare_response_function_bound_on_instance(self):
        ep = anthropic_ep.AnthropicChatHandler()
        assert ep.prepare_response_function is (
            anthropic_ep.AnthropicChatHandler.prepare_response_function
        )


class TestAnthropicChatHandlerRegistration:
    def test_defaults(self):
        ep = anthropic_ep.AnthropicChatHandler()
        assert ep.name == "v1/messages"
        assert ep.method == "POST"
        assert ep._dont_add_api_prefix is True
        assert ep._ep_types_str == ["anthropic"]
        assert ep.direct_return is False

    def test_custom_ep_name_respected(self):
        ep = anthropic_ep.AnthropicChatHandler(ep_name="custom/messages")
        assert ep.name == "custom/messages"

    def test_custom_api_types_respected(self):
        ep = anthropic_ep.AnthropicChatHandler(api_types=["anthropic", "vllm"])
        assert ep._ep_types_str == ["anthropic", "vllm"]
