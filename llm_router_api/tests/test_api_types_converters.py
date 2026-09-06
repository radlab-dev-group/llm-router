"""
Unit tests for ``llm_router_api.core.api_types``.

Covers the endpoint paths exposed by each API type descriptor (vLLM,
LM Studio, Ollama, Anthropic) and the payload/response converters
between OpenAI, Ollama and Anthropic formats.  Pure functions only.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402

from llm_router_api.core.api_types.anthropic import (
    AnthropicConverters,
    AnthropicType,
)  # noqa: E402
from llm_router_api.core.api_types.lmstudio import LMStudioApiType  # noqa: E402
from llm_router_api.core.api_types.ollama import (  # noqa: E402
    OllamaConverters,
    OllamaType,
)
from llm_router_api.core.api_types.vllm import VLLMConverters, VllmType  # noqa: E402


class TestEndpoints:
    def test_vllm_endpoints(self):
        api = VllmType()
        assert api.chat_ep() == "v1/chat/completions"
        assert api.responses_ep() == "v1/responses"
        assert api.embeddings_ep() == "v1/embeddings"

    def test_lmstudio_inherits_vllm_endpoints(self):
        assert LMStudioApiType is not VllmType
        api = LMStudioApiType()
        assert api.chat_ep() == "v1/chat/completions"
        assert api.responses_ep() == "v1/responses"
        assert api.embeddings_ep() == "v1/embeddings"

    def test_ollama_endpoints(self):
        api = OllamaType()
        assert api.chat_ep() == "/api/chat"
        assert api.responses_ep() == "v1/responses"
        assert api.embeddings_ep() == "api/embed"
        assert api.messages_ep() == "/v1/messages?beta=true"

    def test_anthropic_endpoints(self):
        api = AnthropicType()
        assert api.chat_ep() == "/v1/messages"
        assert api.responses_ep() == "v1/responses"
        assert api.embeddings_ep() == "v1/embeddings"

    @pytest.mark.parametrize(
        "api_type_cls",
        [VllmType, LMStudioApiType, OllamaType, AnthropicType],
    )
    def test_completions_endpoint_equals_chat_endpoint(self, api_type_cls):
        api = api_type_cls()
        assert api.completions_ep() == api.chat_ep()


class TestVLLMPayloadConverter:
    def test_parameter_renaming_and_removal(self):
        params = {
            "max_new_tokens": 100,
            "model_name": "model-x",
            "language": "en",
            "temperature": 0.7,
        }
        result = VLLMConverters.Payload.convert_payload(params)
        assert result["max_tokens"] == 100
        assert result["model"] == "model-x"
        assert "language" not in result
        # Original (vLLM-style) keys are removed.
        assert "max_new_tokens" not in result
        assert "model_name" not in result
        # Unrelated parameters are preserved.
        assert result["temperature"] == 0.7

    def test_sub_one_max_tokens_removed(self):
        params = {"max_new_tokens": 0, "model_name": "model-x"}
        result = VLLMConverters.Payload.convert_payload(params)
        assert "max_tokens" not in result
        assert result["model"] == "model-x"


class TestAnthropicPayloadConverter:
    def test_system_prompt_extracted(self):
        params = {
            "model": "claude-3",
            "messages": [
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
        }
        result = AnthropicConverters.Payload.convert_payload(params)
        assert result["system"] == "be brief"
        assert [m["role"] for m in result["messages"]] == ["user", "assistant"]
        assert result["messages"][0]["content"] == "hi"
        assert result["model"] == "claude-3"

    def test_default_max_tokens(self):
        params = {
            "model": "claude-3",
            "messages": [{"role": "user", "content": "hi"}],
        }
        result = AnthropicConverters.Payload.convert_payload(params)
        assert result["max_tokens"] == 4096

    def test_explicit_max_tokens_and_optionals(self):
        params = {
            "model": "claude-3",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 128,
            "stream": True,
            "temperature": 0.2,
            "top_p": 0.9,
        }
        result = AnthropicConverters.Payload.convert_payload(params)
        assert result["max_tokens"] == 128
        assert result["stream"] is True
        assert result["temperature"] == 0.2
        assert result["top_p"] == 0.9
        assert "stop_sequences" not in result

    @pytest.mark.parametrize(
        "stop,expected",
        [("STOP", ["STOP"]), (["a", "b"], ["a", "b"])],
    )
    def test_stop_normalized_to_list(self, stop, expected):
        params = {
            "model": "claude-3",
            "messages": [{"role": "user", "content": "hi"}],
            "stop": stop,
        }
        result = AnthropicConverters.Payload.convert_payload(params)
        assert result["stop_sequences"] == expected


class TestAnthropicResponseConverters:
    def test_from_openai_full(self):
        response = {
            "id": "cmpl-1",
            "model": "gpt-4",
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }
        converted = AnthropicConverters.FromOpenAI.convert_response(response)
        assert converted["id"] == "cmpl-1"
        assert converted["type"] == "message"
        assert converted["role"] == "assistant"
        assert converted["content"] == [{"type": "text", "text": "hello"}]
        assert converted["model"] == "gpt-4"
        assert converted["stop_reason"] == "stop"
        assert converted["usage"] == {"input_tokens": 10, "output_tokens": 20}

    def test_from_openai_empty_choices(self):
        converted = AnthropicConverters.FromOpenAI.convert_response(
            {"id": "cmpl-2", "choices": []}
        )
        assert converted["content"] == []
        assert converted["stop_reason"] is None
        assert converted["usage"] == {"input_tokens": 0, "output_tokens": 0}

    def test_from_ollama_done(self):
        response = {
            "message": {"content": "hi there"},
            "done": True,
            "prompt_eval_count": 5,
            "eval_count": 7,
            "model": "llama3",
        }
        converted = AnthropicConverters.FromOllama.convert_response(response)
        assert converted["id"].startswith("ollama-")
        assert converted["content"] == [{"type": "text", "text": "hi there"}]
        assert converted["stop_reason"] == "end_turn"
        assert converted["usage"] == {"input_tokens": 5, "output_tokens": 7}

    def test_from_ollama_not_done_and_empty_content(self):
        converted = AnthropicConverters.FromOllama.convert_response(
            {"message": {"content": ""}, "done": False}
        )
        assert converted["content"] == []
        assert converted["stop_reason"] is None
        assert converted["usage"] == {"input_tokens": 0, "output_tokens": 0}


class TestOllamaEmbeddingConverter:
    def test_embeddings_and_usage_mapped(self):
        response = {
            "model": "nomic-embed-text",
            "data": [
                {"embedding": [0.1, 0.2]},
                {"embedding": [0.3, 0.4]},
            ],
            "usage": {"prompt_tokens": 4, "total_tokens": 6},
        }
        converted = OllamaConverters.FromOpenAI.convert_embedding(response)
        assert converted["model"] == "nomic-embed-text"
        # Order is preserved.
        assert converted["embeddings"] == [[0.1, 0.2], [0.3, 0.4]]
        assert converted["prompt_eval_count"] == 4
        assert converted["total_tokens"] == 6

    def test_missing_usage_defaults_to_zero(self):
        converted = OllamaConverters.FromOpenAI.convert_embedding(
            {"model": "n", "data": []}
        )
        assert converted["embeddings"] == []
        assert converted["prompt_eval_count"] == 0
        assert converted["total_tokens"] == 0
