"""
Unit tests for the OpenAI‑compatible endpoints in
``llm_router_api.endpoints.builtin.openai``.

Covered without network/Flask:

* ``OpenAIResponseHandler.prepare_response_function`` – Ollama, Anthropic
  and passthrough branches (the converters themselves are covered by the
  core api_types tests);
* ``OpenAIEmbeddingsHandler.prepare_response_function`` – embedding
  conversion vs. passthrough;
* ``OpenAIModelsHandler`` / ``OpenAIModelsV1Handler`` – payload shape and
  the ``timestamp_as_int`` difference;
* registration wiring (``ep_name``, ``method``, ``api_types``,
  ``dont_add_api_prefix``) of every handler in the module.
"""

from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402

from llm_router_api.base.constants_base import (  # noqa: E402
    OPENAI_COMPATIBLE_PROVIDERS,
)
from llm_router_api.endpoints.builtin import openai as openai_ep  # noqa: E402


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

_ANTHROPIC_CHAT = {
    "id": "msg_1",
    "role": "assistant",
    "content": [{"type": "text", "text": "hello"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 2, "output_tokens": 3},
}

_OPENAI_EMBEDDINGS = {
    "model": "m1",
    "data": [{"object": "embedding", "index": 0, "embedding": [0.5, 0.6]}],
    "usage": {"prompt_tokens": 7, "total_tokens": 7},
}

_OLLAMA_EMBEDDINGS = {
    "model": "m1",
    "embeddings": [[0.5, 0.6]],
    "prompt_eval_count": 7,
}


# --------------------------------------------------------------------------- #
# OpenAIResponseHandler.prepare_response_function
# --------------------------------------------------------------------------- #


class TestOpenAIResponseHandlerConverters:
    def test_ollama_response_converted_to_openai(self):
        out = openai_ep.OpenAIResponseHandler.prepare_response_function(
            _FakeResponse(_OLLAMA_CHAT)
        )
        assert out["object"] == "chat.completion"
        assert out["model"] == "m1"
        assert out["choices"][0]["message"]["content"] == "Cześć!"
        assert out["choices"][0]["finish_reason"] == "stop"
        assert out["usage"]["prompt_tokens"] == 3
        assert out["usage"]["completion_tokens"] == 4

    def test_anthropic_response_converted_to_openai(self):
        out = openai_ep.OpenAIResponseHandler.prepare_response_function(
            _FakeResponse(_ANTHROPIC_CHAT)
        )
        assert out["object"] == "chat.completion"
        assert out["id"] == "msg_1"
        assert out["choices"][0]["message"]["content"] == "hello"
        assert out["choices"][0]["finish_reason"] == "end_turn"
        assert out["usage"] == {
            "prompt_tokens": 2,
            "completion_tokens": 3,
            "total_tokens": 5,
        }

    def test_ollama_marker_wins_over_anthropic(self):
        body = dict(
            _ANTHROPIC_CHAT,
            message=_OLLAMA_CHAT["message"],
            prompt_eval_count=3,
            eval_count=4,
        )
        out = openai_ep.OpenAIResponseHandler.prepare_response_function(
            _FakeResponse(body)
        )
        # the "message" branch (Ollama converter) is taken, not Anthropic
        assert out["object"] == "chat.completion"
        assert out["choices"][0]["message"]["content"] == "Cześć!"
        assert out["usage"]["prompt_tokens"] == 3
        assert out["usage"]["completion_tokens"] == 4

    def test_unknown_shape_passes_through(self):
        body = {"foo": "bar"}
        out = openai_ep.OpenAIResponseHandler.prepare_response_function(
            _FakeResponse(body)
        )
        assert out is body


# --------------------------------------------------------------------------- #
# OpenAIEmbeddingsHandler.prepare_response_function
# --------------------------------------------------------------------------- #


class TestOpenAIEmbeddingsHandler:
    def test_ollama_embeddings_converted_to_openai(self):
        out = openai_ep.OpenAIEmbeddingsHandler.prepare_response_function(
            _FakeResponse(_OLLAMA_EMBEDDINGS)
        )
        assert out["object"] == "list"
        assert out["data"][0]["embedding"] == [0.5, 0.6]
        assert out["usage"] == {"prompt_tokens": 7, "total_tokens": 7}

    def test_openai_shape_passes_through(self):
        out = openai_ep.OpenAIEmbeddingsHandler.prepare_response_function(
            _FakeResponse(_OPENAI_EMBEDDINGS)
        )
        assert out is _OPENAI_EMBEDDINGS


# --------------------------------------------------------------------------- #
# OpenAIModelsHandler / V1
# --------------------------------------------------------------------------- #


def _mock_dispatcher(ep, tags_list):
    ep._model_handler = mock.Mock()
    ep._model_handler.list_active_models.return_value = {"group": tags_list}
    ep._api_type_dispatcher = mock.Mock()
    ep._api_type_dispatcher.tags.return_value = tags_list


_TAGS = [
    {"id": "m-1", "object": "model", "owned_by": "vllm", "input_size": 100},
    {"id": "m-2", "object": "model", "owned_by": "ollama", "input_size": 200},
]


class TestOpenAIModelsHandler:
    def test_payload_shape(self):
        ep = openai_ep.OpenAIModelsHandler()
        _mock_dispatcher(ep, _TAGS)
        out = ep.prepare_payload(None)
        assert out["object"] == "list"
        assert len(out["data"]) == 2
        assert out["data"][0] == {
            "id": "m-1",
            "object": "model",
            "created": out["data"][0]["created"],
            "owned_by": "vllm",
        }
        assert "response_time" in out

    def test_created_is_float_by_default(self):
        ep = openai_ep.OpenAIModelsHandler()
        _mock_dispatcher(ep, _TAGS)
        out = ep.prepare_payload(None)
        assert isinstance(out["data"][0]["created"], float)

    def test_dispatcher_called_with_merged_list(self):
        ep = openai_ep.OpenAIModelsHandler()
        _mock_dispatcher(ep, _TAGS)
        ep.prepare_payload(None)
        ep._api_type_dispatcher.tags.assert_called_once_with(
            models_config={"group": _TAGS}, merge_to_list=True
        )

    def test_without_model_handler_empty_config(self):
        ep = openai_ep.OpenAIModelsHandler()
        assert ep.model_handler is None
        ep._api_type_dispatcher = mock.Mock()
        ep._api_type_dispatcher.tags.return_value = []
        out = ep.prepare_payload(None)
        ep._api_type_dispatcher.tags.assert_called_once_with(
            models_config={}, merge_to_list=True
        )
        assert out["data"] == []


class TestOpenAIModelsV1Handler:
    def test_created_is_int(self):
        ep = openai_ep.OpenAIModelsV1Handler()
        _mock_dispatcher(ep, _TAGS)
        out = ep.prepare_payload(None)
        assert isinstance(out["data"][0]["created"], int)

    def test_registration(self):
        ep = openai_ep.OpenAIModelsV1Handler()
        assert ep.name == "v1/models"
        assert ep.method == "GET"
        assert ep._dont_add_api_prefix is True
        assert ep._ep_types_str == OPENAI_COMPATIBLE_PROVIDERS


# --------------------------------------------------------------------------- #
# Registration wiring of every handler
# --------------------------------------------------------------------------- #


class TestRegistrationWiring:
    @pytest.mark.parametrize(
        ("cls", "ep_name", "method", "dont_prefix", "api_types"),
        [
            (
                openai_ep.OpenAIResponsesHandler,
                "responses",
                "POST",
                True,
                OPENAI_COMPATIBLE_PROVIDERS,
            ),
            (
                openai_ep.OpenAIResponsesV1Handler,
                "v1/responses",
                "POST",
                True,
                OPENAI_COMPATIBLE_PROVIDERS,
            ),
            (
                openai_ep.OpenAICompletionHandler,
                "chat/completions",
                "POST",
                False,
                OPENAI_COMPATIBLE_PROVIDERS,
            ),
            (
                openai_ep.OpenAIEmbeddingsHandler,
                "embeddings",
                "POST",
                True,
                OPENAI_COMPATIBLE_PROVIDERS,
            ),
            (
                openai_ep.OpenAIEmbeddingsV1Handler,
                "v1/embeddings",
                "POST",
                True,
                OPENAI_COMPATIBLE_PROVIDERS + ["anthropic"],
            ),
            (
                openai_ep.OpenAICompletionHandlerWOApi,
                "chat/completions",
                "POST",
                True,
                OPENAI_COMPATIBLE_PROVIDERS,
            ),
            (
                openai_ep.OpenAiV1ChatCompletion,
                "/v1/chat/completions",
                "POST",
                True,
                OPENAI_COMPATIBLE_PROVIDERS,
            ),
            (
                openai_ep.OpenAIModelsHandler,
                "models",
                "GET",
                True,
                OPENAI_COMPATIBLE_PROVIDERS,
            ),
        ],
    )
    def test_handler_registration(
        self, cls, ep_name, method, dont_prefix, api_types
    ):
        ep = cls()
        assert ep.name == ep_name
        assert ep.method == method
        assert ep._dont_add_api_prefix is dont_prefix
        assert ep._ep_types_str == api_types

    def test_chat_handlers_bind_prepare_response_function(self):
        ep = openai_ep.OpenAiV1ChatCompletion()
        assert ep.prepare_response_function is (
            openai_ep.OpenAIResponseHandler.prepare_response_function
        )

    def test_chat_handler_prepare_payload_passthrough(self):
        ep = openai_ep.OpenAiV1ChatCompletion()
        params = {"model": "m", "messages": [{"role": "user", "content": "x"}]}
        out = ep.prepare_payload(params)
        assert out["model"] == "m"
        assert "response_time" in out
        assert "response_time" not in params
