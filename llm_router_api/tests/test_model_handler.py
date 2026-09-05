"""
Unit tests for ``llm_router_api.core.model_handler``.

Covers ``ApiModel.from_config`` / ``as_dict`` mapping and the
``ModelHandler`` provider selection, delegation and model listing
behaviour.  The provider chooser is a mock; config files use ``tmp_path``.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from unittest import mock  # noqa: E402

import pytest  # noqa: E402

from llm_router_api.core.model_handler import ApiModel, ModelHandler  # noqa: E402


def _write_config(tmp_path, payload) -> str:
    path = tmp_path / "models-config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


class TestApiModelFromConfig:
    def test_full_mapping(self):
        cfg = {
            "id": "pid1",
            "api_host": "http://h",
            "api_type": "vllm",
            "api_token": "tok",
            "input_size": "8192",
            "model_path": "/mp",
            "keep_alive": "5m",
            "tool_calling": True,
            "is_embedding": False,
        }
        model = ApiModel.from_config("my-model", cfg)
        assert model.id == "pid1"
        assert model.name == "my-model"
        assert model.api_host == "http://h"
        assert model.api_type == "vllm"
        assert model.api_token == "tok"
        assert model.input_size == 8192
        assert isinstance(model.input_size, int)
        assert model.model_path == "/mp"
        assert model.keep_alive == "5m"
        assert model.tool_calling is True
        assert model.is_embedding is False

    def test_int_input_size(self):
        cfg = {
            "id": "p",
            "api_host": "h",
            "api_type": "ollama",
            "input_size": 100,
        }
        assert ApiModel.from_config("m", cfg).input_size == 100

    def test_defaults_for_missing_optional_keys(self):
        cfg = {"id": "p", "api_host": "h", "api_type": "ollama", "input_size": 100}
        model = ApiModel.from_config("m", cfg)
        assert model.api_token == ""
        assert model.model_path == ""
        assert model.keep_alive == ""
        assert model.tool_calling is False
        assert model.is_embedding is False

    def test_missing_required_key_raises(self):
        with pytest.raises(KeyError):
            ApiModel.from_config("m", {"id": "p"})  # no api_host / api_type


class TestApiModelAsDict:
    def test_contains_all_fields(self):
        model = ApiModel.from_config(
            "m",
            {
                "id": "p",
                "api_host": "h",
                "api_type": "ollama",
                "input_size": 10,
            },
        )
        as_dict = model.as_dict()
        assert set(as_dict) == {
            "id",
            "name",
            "api_host",
            "api_type",
            "api_token",
            "input_size",
            "model_path",
            "keep_alive",
            "tool_calling",
            "is_embedding",
        }
        assert as_dict["name"] == "m"


class TestModelHandler:
    @pytest.fixture
    def handler(self, tmp_path):
        config = {
            "active_models": {"vllm": ["m1"], "ollama": ["m2"]},
            "vllm": {
                "m1": {
                    "providers": [
                        {
                            "id": "a",
                            "api_host": "h1",
                            "api_type": "vllm",
                            "input_size": 8,
                            "model_path": "mp",
                            "api_token": "secret",
                        }
                    ]
                }
            },
            "ollama": {
                "m2": {
                    "providers": [
                        {
                            "id": "b",
                            "api_host": "h2",
                            "api_type": "ollama",
                            "input_size": 4,
                        }
                    ]
                }
            },
        }
        chooser = mock.Mock()
        chooser.get_provider.return_value = {
            "id": "b",
            "api_host": "h2",
            "api_type": "ollama",
            "input_size": 4,
        }
        path = _write_config(tmp_path, config)
        handler = ModelHandler(path, chooser)
        return handler, config, chooser

    def test_fake_returns_first_provider(self, handler):
        model_handler, config, _ = handler
        provider = model_handler.get_model_provider("m1", fake=True)
        assert isinstance(provider, ApiModel)
        assert provider.api_host == config["vllm"]["m1"]["providers"][0]["api_host"]
        # The chooser must not be consulted in fake mode.
        model_handler.provider_chooser.get_provider.assert_not_called()

    def test_chooser_provider_used_when_not_fake(self, handler):
        model_handler, _, chooser = handler
        provider = model_handler.get_model_provider("m2")
        assert provider.api_host == "h2"
        chooser.get_provider.assert_called_once()

    def test_empty_providers_returns_none(self, handler):
        model_handler, _, _ = handler
        # "m1" has providers, so point at a model with an empty list.
        model_handler.api_model_config.models_configs["empty"] = {"providers": []}
        assert model_handler.get_model_provider("empty") is None

    def test_chooser_none_returns_none(self, handler):
        model_handler, _, chooser = handler
        chooser.get_provider.return_value = None
        assert model_handler.get_model_provider("m2") is None

    def test_put_model_provider_delegates(self, handler):
        model_handler, _, chooser = handler
        provider = {"id": "b"}
        model_handler.put_model_provider("m2", provider, options={"x": 1})
        chooser.put_provider.assert_called_once_with(
            model_name="m2", provider=provider, options={"x": 1}
        )

    def test_list_active_models_groups_and_strips_secrets(self, handler):
        model_handler, _, _ = handler
        listing = model_handler.list_active_models()
        assert set(listing) == {"vllm", "ollama"}
        m1 = listing["vllm"][0]
        assert m1["name"] == "m1"
        assert m1["id"] == "a"
        assert "model_path" not in m1
        assert "api_token" not in m1
        m2 = listing["ollama"][0]
        assert m2["name"] == "m2"
