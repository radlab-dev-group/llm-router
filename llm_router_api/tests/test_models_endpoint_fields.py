"""
Tests for M6 — ``/models`` responses must not contain fabricated constants.

The model descriptor fields ``type``, ``state``, ``compatibility_type`` and
``quantization`` must be sourced from the real per-provider configuration
when available, and fall back to ``None`` otherwise — never fake values like
``"vllm"``, ``"not-loaded"``, ``"mlx"`` or ``"4bit"``.
"""

from typing import Any, Dict, List

import pytest

from llm_router_api.core.api_types.types_i import ApiTypesI
from llm_router_api.core.api_types.dispatcher import ApiTypesDispatcher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Wrap a flat list of provider dicts into the ``{group: [...]}`` schema."""
    return {"openai_models": entries}


def _first_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    tagged = ApiTypesI.tags(_make_config([entry]))
    return next(iter(tagged.values()))[0]


_BASE_ENTRY = {
    "name": "google/gemma-3-12b-it",
    "api_type": "vllm",
    "api_host": "http://localhost:7000",
    "api_token": "secret",
    "input_size": 56000,
    "model_path": "/models/gemma",
    "keep_alive": True,
    "tool_calling": True,
    "weight": 1.0,
}


# ---------------------------------------------------------------------------
# get_models_list — unknown provider data → None (no fake constants)
# ---------------------------------------------------------------------------


class TestGetModelsListDefaults:
    def test_no_fabricated_constants_when_unconfigured(self):
        out = _first_entry(dict(_BASE_ENTRY))
        # Real data from config
        assert out["id"] == "google/gemma-3-12b-it"
        assert out["owned_by"] == "vllm"
        assert out["input_size"] == 56000
        assert out["host"] == "http://localhost:7000"
        assert out["path"] == "/models/gemma"
        # Must NOT be hardcoded fake values
        assert out["state"] is None
        assert out["compatibility_type"] is None
        assert out["quantization"] is None
        assert out["publisher"] is None
        # type falls back to the provider's own api_type (real data)
        assert out["type"] == "vllm"

    def test_ollama_entry_not_mislabeled_as_vllm(self):
        out = _first_entry(
            {
                **_BASE_ENTRY,
                "name": "gpt-oss:20b",
                "api_type": "ollama",
                "input_size": 256000,
            }
        )
        assert out["type"] == "ollama"
        assert out["owned_by"] == "ollama"
        assert out["state"] is None
        assert out["compatibility_type"] is None
        assert out["quantization"] is None

    def test_openai_entry_not_mislabeled_as_vllm(self):
        out = _first_entry(
            {**_BASE_ENTRY, "name": "gpt-3.5-turbo", "api_type": "openai"}
        )
        assert out["type"] == "openai"
        assert out["state"] is None
        assert out["compatibility_type"] is None
        assert out["quantization"] is None

    def test_lmstudio_entry_defaults(self):
        out = _first_entry(
            {**_BASE_ENTRY, "name": "qwen2.5-7b", "api_type": "lmstudio"}
        )
        assert out["type"] == "lmstudio"
        assert out["state"] is None
        assert out["compatibility_type"] is None
        assert out["quantization"] is None


# ---------------------------------------------------------------------------
# get_models_list — real per-provider data is honored
# ---------------------------------------------------------------------------


class TestGetModelsListRealData:
    def test_quantization_and_compat_from_config(self):
        out = _first_entry(
            {**_BASE_ENTRY, "quantization": "Q8_0", "compatibility_type": "gguf"}
        )
        assert out["quantization"] == "Q8_0"
        assert out["compatibility_type"] == "gguf"
        # state still not fabricated
        assert out["state"] is None

    def test_state_from_config(self):
        out = _first_entry({**_BASE_ENTRY, "state": "loaded"})
        assert out["state"] == "loaded"

    def test_publisher_and_arch_from_config(self):
        out = _first_entry({**_BASE_ENTRY, "publisher": "google", "arch": "gemma-3"})
        assert out["publisher"] == "google"
        assert out["arch"] == "gemma-3"

    def test_explicit_type_overrides_api_type(self):
        out = _first_entry({**_BASE_ENTRY, "type": "llm"})
        assert out["type"] == "llm"


# ---------------------------------------------------------------------------
# dispatcher.tags — end-to-end merge_to_list path used by /models endpoints
# ---------------------------------------------------------------------------


class TestDispatcherTags:
    def test_merged_list_fields(self):
        config = _make_config(
            [
                {**_BASE_ENTRY, "quantization": "4bit", "state": "loaded"},
                {**_BASE_ENTRY, "name": "gpt-oss:20b", "api_type": "ollama"},
            ]
        )
        res = ApiTypesDispatcher.tags(models_config=config, merge_to_list=True)
        assert isinstance(res, list) and len(res) == 2
        by_name = {m["id"]: m for m in res}
        assert by_name["google/gemma-3-12b-it"]["quantization"] == "4bit"
        assert by_name["google/gemma-3-12b-it"]["state"] == "loaded"
        assert by_name["gpt-oss:20b"]["type"] == "ollama"
        assert by_name["gpt-oss:20b"]["quantization"] is None
        assert by_name["gpt-oss:20b"]["state"] is None

    def test_grouped_mapping_per_api_type(self):
        config = _make_config(
            [
                {**_BASE_ENTRY, "api_type": "vllm"},
                {**_BASE_ENTRY, "name": "gpt-oss:20b", "api_type": "ollama"},
            ]
        )
        grouped = ApiTypesDispatcher.tags(models_config=config, merge_to_list=False)
        assert set(grouped.keys()) == {"vllm", "ollama"}
        assert len(grouped["vllm"]) == 1
        assert len(grouped["ollama"]) == 1

    def test_unknown_fields_never_fake(self):
        for api_type in ("vllm", "ollama", "openai", "lmstudio"):
            out = _first_entry({**_BASE_ENTRY, "api_type": api_type})
            for field in (
                "state",
                "compatibility_type",
                "quantization",
                "publisher",
                "arch",
            ):
                assert out[field] is None, (api_type, field)


# ---------------------------------------------------------------------------
# LM Studio endpoint handler formatting
# ---------------------------------------------------------------------------


class _FakeDispatcher:
    def __init__(self, models_data: List[Dict[str, Any]]):
        self._data = models_data

    def tags(self, models_config=None, merge_to_list=False):
        return self._data


class TestLmStudioModelsFormat:
    def _run_handler(self, models_data: List[Dict[str, Any]]):
        import llm_router_api.endpoints.builtin.lmstudio as lm_mod

        handler = lm_mod.LmStudioModelsHandler.__new__(lm_mod.LmStudioModelsHandler)
        handler._api_type_dispatcher = _FakeDispatcher(models_data)
        handler._model_handler = type(
            "MH",
            (),
            {
                "list_active_models": staticmethod(lambda: {"openai_models": []}),
            },
        )()
        fmt = getattr(
            lm_mod.LmStudioModelsHandler,
            "_LmStudioModelsHandler__proper_models_list_format",
        )
        return fmt(handler)

    def test_no_fake_constants(self):
        models = [
            {
                "id": "qwen2.5-7b",
                "object": "model",
                "type": "llm",
                "publisher": None,
                "arch": None,
                "compatibility_type": None,
                "quantization": None,
                "state": None,
                "max_context_length": 32768,
            }
        ]
        resp = self._run_handler(models)
        data = resp["data"]
        assert resp["object"] == "list"
        assert data[0]["compatibility_type"] is None
        assert data[0]["quantization"] is None
        assert data[0]["state"] is None
        assert data[0]["type"] == "llm"
        assert data[0]["max_context_length"] == 32768

    def test_real_data_passthrough(self):
        models = [
            {
                "id": "qwen2.5-7b",
                "object": "model",
                "type": "llm",
                "publisher": "qwen",
                "arch": "qwen2.5",
                "compatibility_type": "gguf",
                "quantization": "Q8_0",
                "state": "loaded",
                "max_context_length": 32768,
            }
        ]
        data = self._run_handler(models)["data"]
        assert data[0]["quantization"] == "Q8_0"
        assert data[0]["state"] == "loaded"
        assert data[0]["compatibility_type"] == "gguf"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
