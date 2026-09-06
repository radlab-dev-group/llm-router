"""
Unit tests for ``llm_router_api.core.model_config.ApiModelConfig``.

Covers JSON loading, active-model extraction, per-model configuration
building and provider-identifier uniqueness validation.  Config files are
written to ``tmp_path``; no external services required.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402

from llm_router_api.core.model_config import ApiModelConfig  # noqa: E402


def _write_config(tmp_path, payload) -> str:
    path = tmp_path / "models-config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


class TestValidConfig:
    def test_active_models_and_configs(self, tmp_path):
        path = _write_config(
            tmp_path,
            {
                "active_models": {"openapi": ["m1"], "vllm": ["m2"]},
                "openapi": {"m1": {"providers": [{"id": "p1"}]}},
                "vllm": {"m2": {"providers": [{"id": "p2"}]}},
            },
        )
        config = ApiModelConfig(path)
        assert config.active_models == {"openapi": ["m1"], "vllm": ["m2"]}
        assert config.models_configs == {
            "m1": {"providers": [{"id": "p1"}]},
            "m2": {"providers": [{"id": "p2"}]},
        }

    def test_empty_active_models_yields_empty(self, tmp_path):
        path = _write_config(tmp_path, {"active_models": {}, "openapi": {}})
        config = ApiModelConfig(path)
        assert config.active_models == {}
        assert config.models_configs == {}

    def test_unique_provider_ids_accepted(self, tmp_path):
        path = _write_config(
            tmp_path,
            {
                "active_models": {"openapi": ["m1", "m2"]},
                "openapi": {
                    "m1": {"providers": [{"id": "a"}]},
                    "m2": {"providers": [{"id": "b"}]},
                },
            },
        )
        config = ApiModelConfig(path)  # must not raise
        assert set(config.models_configs) == {"m1", "m2"}


class TestErrorPaths:
    def test_missing_file_raises_file_not_found(self, tmp_path):
        missing = tmp_path / "does-not-exist.json"
        with pytest.raises(FileNotFoundError):
            ApiModelConfig(str(missing))

    def test_invalid_json_raises_runtime_error(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(RuntimeError, match="Invalid JSON format"):
            ApiModelConfig(str(path))

    def test_model_without_providers_raises_key_error(self, tmp_path):
        path = _write_config(
            tmp_path,
            {
                "active_models": {"openapi": ["m1"]},
                "openapi": {"m1": {"api_host": "x"}},
            },
        )
        with pytest.raises(KeyError, match="openapi:m1 has no providers!"):
            ApiModelConfig(path)

    def test_duplicate_provider_ids_raise_value_error(self, tmp_path):
        path = _write_config(
            tmp_path,
            {
                "active_models": {"openapi": ["m1", "m2"]},
                "openapi": {
                    "m1": {"providers": [{"id": "dup"}, {"id": "other"}]},
                    "m2": {"providers": [{"id": "dup"}]},
                },
            },
        )
        with pytest.raises(ValueError) as excinfo:
            ApiModelConfig(path)
        # The offending provider id is listed in the message.
        assert "dup" in str(excinfo.value)
