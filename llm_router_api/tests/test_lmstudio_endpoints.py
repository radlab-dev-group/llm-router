"""
Unit tests for the LM Studio endpoints in
``llm_router_api.endpoints.builtin.lmstudio``.

Covered without network/Flask:

* ``LmStudioModelsHandler.prepare_payload`` – the mapping from internal
  model tags to the LM Studio ``/v0/models`` schema (publisher fallback,
  embedding vs. llm type, static fields);
* ``LLMStudioChatV0Handler`` – registration wiring and the inherited
  OpenAI‑compatible response conversion.
"""

from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402

from llm_router_api.endpoints.builtin import lmstudio as lmstudio_ep  # noqa: E402


def _mock_dispatcher(ep, tags_list):
    ep._model_handler = mock.Mock()
    ep._model_handler.list_active_models.return_value = {"g": tags_list}
    ep._api_type_dispatcher = mock.Mock()
    ep._api_type_dispatcher.tags.return_value = tags_list


class TestLmStudioModelsHandler:
    def test_full_entry_mapping(self):
        ep = lmstudio_ep.LmStudioModelsHandler()
        tag = {
            "id": "org/model-x",
            "object": "model",
            "name": "org/model-x",
            "publisher": "org",
            "is_embedding": True,
            "arch": "lsm-arch",
            "compatibility_type": "lmstudio",
            "quantization": "q4",
            "max_context_length": 8192,
        }
        _mock_dispatcher(ep, [tag])
        out = ep.prepare_payload(None)
        assert out["object"] == "list"
        assert out["data"] == [
            {
                "id": "org/model-x",
                "object": "model",
                "type": "embeddings",
                "publisher": "org",
                "arch": "lsm-arch",
                "compatibility_type": "lmstudio",
                "quantization": "q4",
                "state": "loaded",
                "max_context_length": 8192,
            }
        ]
        assert "response_time" in out

    def test_publisher_fallback_from_slashed_name(self):
        ep = lmstudio_ep.LmStudioModelsHandler()
        tag = {
            "id": "vendor/llama-3-8b",
            "object": "model",
            "max_context_length": 100,
        }
        _mock_dispatcher(ep, [tag])
        out = ep.prepare_payload(None)
        assert out["data"][0]["publisher"] == "vendor"
        assert out["data"][0]["type"] == "llm"
        assert out["data"][0]["arch"] == ""
        assert out["data"][0]["compatibility_type"] == ""
        assert out["data"][0]["quantization"] == ""

    def test_publisher_empty_when_name_has_no_slash(self):
        ep = lmstudio_ep.LmStudioModelsHandler()
        tag = {
            "id": "plain-model",
            "object": "model",
            "name": "plain-model",
            "max_context_length": 10,
        }
        _mock_dispatcher(ep, [tag])
        out = ep.prepare_payload(None)
        assert out["data"][0]["publisher"] == ""

    def test_name_falls_back_to_id(self):
        ep = lmstudio_ep.LmStudioModelsHandler()
        tag = {"id": "solo/model", "object": "model", "max_context_length": 1}
        _mock_dispatcher(ep, [tag])
        out = ep.prepare_payload(None)
        assert out["data"][0]["publisher"] == "solo"
        assert out["data"][0]["id"] == "solo/model"

    def test_missing_max_context_length_raises_key_error(self):
        # current contract: ``max_context_length`` is mandatory per tag
        ep = lmstudio_ep.LmStudioModelsHandler()
        _mock_dispatcher(ep, [{"id": "m", "object": "model"}])
        with pytest.raises(KeyError):
            ep.prepare_payload(None)

    def test_without_model_handler_empty_config(self):
        ep = lmstudio_ep.LmStudioModelsHandler()
        assert ep.model_handler is None
        ep._api_type_dispatcher = mock.Mock()
        ep._api_type_dispatcher.tags.return_value = []
        out = ep.prepare_payload(None)
        ep._api_type_dispatcher.tags.assert_called_once_with(
            models_config={}, merge_to_list=True
        )
        assert out["data"] == []

    def test_guardrail_and_masking_exemption(self):
        ep = lmstudio_ep.LmStudioModelsHandler()
        assert ep.EP_DONT_NEED_GUARDRAIL_AND_MASKING is True
        assert ep.name == "v0/models"
        assert ep.method == "GET"
        assert ep._dont_add_api_prefix is False
        assert ep._ep_types_str == ["lmstudio"]
        assert ep.direct_return is True


class TestLLMStudioChatV0Handler:
    def test_registration(self):
        ep = lmstudio_ep.LLMStudioChatV0Handler()
        assert ep.name == "v0/chat/completions"
        assert ep.method == "POST"
        assert ep._dont_add_api_prefix is False
        assert ep._ep_types_str == ["lmstudio"]
        assert ep.direct_return is False

    def test_prepare_response_function_bound(self):
        ep = lmstudio_ep.LLMStudioChatV0Handler()
        assert ep.prepare_response_function is (
            lmstudio_ep.LLMStudioChatV0Handler.prepare_response_function
        )

    def test_ollama_response_converted(self):
        class _Resp:
            def json(self):
                return {
                    "model": "m1",
                    "message": {"role": "assistant", "content": "ok"},
                    "done": True,
                }

        out = lmstudio_ep.LLMStudioChatV0Handler.prepare_response_function(_Resp())
        assert out["object"] == "chat.completion"
        assert out["choices"][0]["message"]["content"] == "ok"

    def test_prepare_payload_passthrough(self):
        ep = lmstudio_ep.LLMStudioChatV0Handler()
        params = {"model": "m", "prompt": "x"}
        out = ep.prepare_payload(params)
        assert out["model"] == "m"
        assert out["prompt"] == "x"
        assert "response_time" in out
