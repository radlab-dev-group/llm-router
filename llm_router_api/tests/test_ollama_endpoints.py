"""
Unit tests for the Ollama endpoints in
``llm_router_api.endpoints.builtin.ollama``.

Covered without network/Flask:

* ``OllamaEmbeddingsHandler.prepare_response_function`` – OpenAI→Ollama
  embedding conversion vs. passthrough;
* ``OllamaHomeHandler.prepare_payload`` – the plain-text health response and
  the ``direct_return`` side effect;
* ``OllamaTagsHandler.prepare_payload`` – payload shape and dispatcher
  contract (including the no-model-handler case);
* ``OllamaChatHandler`` – pass‑through payload and registration defaults.
"""

from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from llm_router_api.endpoints.builtin import ollama as ollama_ep  # noqa: E402


class _FakeResponse:
    """Minimal stand‑in for a ``requests.Response`` exposing ``.json()``."""

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


_OPENAI_EMBEDDINGS = {
    "object": "list",
    "model": "m1",
    "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}],
    "usage": {"prompt_tokens": 5, "total_tokens": 9},
}

_OLLAMA_EMBEDDINGS = {
    "model": "m1",
    "embeddings": [[0.1, 0.2]],
    "prompt_eval_count": 5,
    "total_tokens": 9,
}


# --------------------------------------------------------------------------- #
# OllamaEmbeddingsHandler
# --------------------------------------------------------------------------- #


class TestOllamaEmbeddingsHandler:
    def test_openai_embeddings_converted_to_ollama(self):
        out = ollama_ep.OllamaEmbeddingsHandler.prepare_response_function(
            _FakeResponse(_OPENAI_EMBEDDINGS)
        )
        assert out["model"] == "m1"
        assert out["embeddings"] == [[0.1, 0.2]]
        assert out["prompt_eval_count"] == 5
        assert out["total_tokens"] == 9

    def test_ollama_shape_passes_through(self):
        out = ollama_ep.OllamaEmbeddingsHandler.prepare_response_function(
            _FakeResponse(_OLLAMA_EMBEDDINGS)
        )
        assert out is _OLLAMA_EMBEDDINGS

    def test_registration(self):
        ep = ollama_ep.OllamaEmbeddingsHandler()
        assert ep.name == "embed"
        assert ep.method == "POST"
        assert ep._dont_add_api_prefix is False
        assert ep._ep_types_str == ["ollama"]


# --------------------------------------------------------------------------- #
# OllamaHomeHandler
# --------------------------------------------------------------------------- #


class TestOllamaHomeHandler:
    def test_returns_plain_text_confirmation(self):
        ep = ollama_ep.OllamaHomeHandler()
        out = ep.prepare_payload(None)
        assert out == "Ollama is running"

    def test_sets_direct_return(self):
        ep = ollama_ep.OllamaHomeHandler()
        assert ep.direct_return is False
        ep.prepare_payload(None)
        assert ep.direct_return is True

    def test_registration(self):
        ep = ollama_ep.OllamaHomeHandler()
        assert ep.name == "/"
        assert ep.method == "GET"
        assert ep._dont_add_api_prefix is True
        assert ep._ep_types_str == ["ollama"]
        assert ep.REQUIRED_ARGS == []
        assert ep.EP_DONT_NEED_GUARDRAIL_AND_MASKING is True


# --------------------------------------------------------------------------- #
# OllamaTagsHandler
# --------------------------------------------------------------------------- #


class TestOllamaTagsHandler:
    def test_payload_shape(self):
        ep = ollama_ep.OllamaTagsHandler()
        tags = [{"name": "m1", "size": 1}, {"name": "m2", "size": 2}]
        ep._model_handler = mock.Mock()
        ep._model_handler.list_active_models.return_value = {"g": tags}
        ep._api_type_dispatcher = mock.Mock()
        ep._api_type_dispatcher.tags.return_value = tags

        out = ep.prepare_payload(None)
        assert out["models"] == tags
        assert "response_time" in out
        ep._api_type_dispatcher.tags.assert_called_once_with(
            models_config={"g": tags}, merge_to_list=True
        )

    def test_empty_model_list(self):
        ep = ollama_ep.OllamaTagsHandler()
        ep._model_handler = mock.Mock()
        ep._model_handler.list_active_models.return_value = {}
        ep._api_type_dispatcher = mock.Mock()
        ep._api_type_dispatcher.tags.return_value = []
        out = ep.prepare_payload({})
        ep._api_type_dispatcher.tags.assert_called_once_with(
            models_config={}, merge_to_list=True
        )
        assert out["models"] == []

    def test_sets_direct_return(self):
        ep = ollama_ep.OllamaTagsHandler()
        ep._model_handler = mock.Mock()
        ep._model_handler.list_active_models.return_value = {}
        ep._api_type_dispatcher = mock.Mock()
        ep._api_type_dispatcher.tags.return_value = []
        ep.prepare_payload(None)
        assert ep.direct_return is True

    def test_registration(self):
        ep = ollama_ep.OllamaTagsHandler()
        assert ep.name == "tags"
        assert ep.method == "GET"
        assert ep._dont_add_api_prefix is False
        assert ep._ep_types_str == ["ollama"]
        assert ep.REQUIRED_ARGS == []
        assert ep.EP_DONT_NEED_GUARDRAIL_AND_MASKING is True


# --------------------------------------------------------------------------- #
# OllamaChatHandler
# --------------------------------------------------------------------------- #


class TestOllamaChatHandler:
    def test_argument_defaults(self):
        ep = ollama_ep.OllamaChatHandler()
        assert ep.REQUIRED_ARGS is None
        assert ep.OPTIONAL_ARGS is None
        assert ep.SYSTEM_PROMPT_NAME is None
        assert ep.name == "chat"
        assert ep.method == "POST"
        assert ep._dont_add_api_prefix is False
        assert ep._ep_types_str == ["ollama"]
        assert ep.direct_return is False

    def test_prepare_payload_passthrough(self):
        ep = ollama_ep.OllamaChatHandler()
        params = {"model": "m", "messages": [{"role": "user", "content": "x"}]}
        out = ep.prepare_payload(params)
        assert out["model"] == "m"
        assert out["messages"] == params["messages"]
        assert "response_time" in out
        assert "response_time" not in params
