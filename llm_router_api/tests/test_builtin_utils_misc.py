"""
Unit tests for the "misc" built‑in utility endpoints in
``llm_router_api.endpoints.builtin.builtin_utils``:

* ``ApiVersion`` – version file parsing (valid/invalid/missing), payload
  shape and registration wiring;
* ``TextListUtilityEndpoint`` – the shared contract of the ``texts``
  endpoints: ``MODEL_CLS`` requirement, payload normalisation
  (texts → user messages, ``model`` field, ``stream`` default),
  ``map_prompt`` injection hook and the ``_prepare_response`` collation.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from llm_router_api.endpoints.builtin.builtin_utils import (  # noqa: E402
    ApiVersion,
    TextListUtilityEndpoint,
)


# --------------------------------------------------------------------------- #
# ApiVersion
# --------------------------------------------------------------------------- #


class TestApiVersionVersionFile:
    def test_valid_version_loaded(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".version").write_text("0.5.2\n", encoding="utf-8")
        ep = ApiVersion()
        assert ep.version == "0.5.2"

    def test_valid_version_with_suffix(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".version").write_text("1.0.2-rc1", encoding="utf-8")
        assert ApiVersion().version == "1.0.2-rc1"

    def test_valid_version_with_dash_suffix(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".version").write_text("1.0.0-rc1", encoding="utf-8")
        assert ApiVersion().version == "1.0.0-rc1"

    def test_missing_file_falls_back_to_not_given(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ep = ApiVersion()
        assert ep.version == "not-given"

    @pytest.mark.parametrize(
        "raw",
        ["banana", "1.2", "1.2.3.4", "v1.2.3", "1.0.2rc", ""],
    )
    def test_invalid_version_raises(self, tmp_path, monkeypatch, raw):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".version").write_text(raw, encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid version format"):
            ApiVersion()


class TestApiVersionPayload:
    def test_prepare_payload(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".version").write_text("2.3.4", encoding="utf-8")
        ep = ApiVersion()
        out = ep.prepare_payload(None)
        assert out["version"] == "2.3.4"
        assert "response_time" in out
        assert ep.direct_return is True

    def test_registration(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        ep = ApiVersion()
        assert ep.name == "version"
        assert ep.method == "GET"
        assert ep._dont_add_api_prefix is False
        assert "builtin" in ep._ep_types_str
        assert ep.EP_DONT_NEED_GUARDRAIL_AND_MASKING is True
        assert ep.REQUIRED_ARGS == []
        assert ep.OPTIONAL_ARGS == []
        assert ep.SYSTEM_PROMPT_NAME is None


# --------------------------------------------------------------------------- #
# TextListUtilityEndpoint
# --------------------------------------------------------------------------- #


class _TextsRequest(BaseModel):
    model_name: str
    texts: List[str]
    stream: bool = False
    stream: bool = False
    stream: bool = False
    stream: bool = False
    stream: bool = False
    stream: bool = False
    stream: bool = False
    stream: bool = False
    stream: bool = False
    stream: bool = False
    stream: bool = False
    stream: bool = False
    stream: bool = False


class _MyTextsEP(TextListUtilityEndpoint):
    """Minimal concrete endpoint on top of the shared texts contract."""

    MODEL_CLS = _TextsRequest

    def __init__(self):
        super().__init__(ep_name="my_texts_ep")

    def _build_results(self, raw_texts: List[str], contents: List[str]):
        return [f"Q({r})" for r in raw_texts]


class _FakeResponse:
    def __init__(self, content: str):
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


class TestTextListUtilityEndpointContract:
    def test_base_class_requires_model_cls(self):
        with pytest.raises(TypeError, match="MODEL_CLS"):
            TextListUtilityEndpoint(ep_name="no_model_cls")

    def test_call_for_each_user_msg_enabled(self):
        ep = _MyTextsEP()
        assert ep._call_for_each_user_msg is True
        assert ep.name == "my_texts_ep"
        assert ep.method == "POST"
        assert ep._ep_types_str == ["builtin"]

    def test_prepare_payload_normalises(self):
        ep = _MyTextsEP()
        out = ep.prepare_payload({"model_name": "m", "texts": ["a", "b"]})
        assert out["model"] == "m"
        assert out["stream"] is False
        assert out["messages"] == [
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
        ]
        assert "texts" not in out
        assert "map_prompt" not in out

    def test_stream_flag_forwarded_when_given(self):
        ep = _MyTextsEP()
        out = ep.prepare_payload({"model_name": "m", "texts": ["a"], "stream": True})
        assert out["stream"] is True

    def test_map_prompt_injected_when_hook_returns_dict(self):
        class _MappedEP(_MyTextsEP):
            def build_map_prompt(self, payload: Dict[str, Any]):
                return {"pl": "prompt-{text}", "en": "prompt-{text}"}

        ep = _MappedEP()
        out = ep.prepare_payload({"model_name": "m", "texts": ["a"]})
        assert out["map_prompt"] == {"pl": "prompt-{text}", "en": "prompt-{text}"}

    def test_prepare_response_collates_and_times(self):
        ep = _MyTextsEP()
        ep._start_time = time.time() - 0.2
        out = ep._prepare_response(
            [_FakeResponse("r1"), _FakeResponse("r2")], ["a", "b"]
        )
        assert out["response"] == ["Q(r1)", "Q(r2)"]
        assert out["generation_time"] >= 0.1

    def test_prepare_response_function_bound_to_prepare_response(self):
        ep = _MyTextsEP()
        assert ep.prepare_response_function == ep._prepare_response


class TestGetChoicesFromResponse:
    def test_openai_choices(self):
        j, choices, assistant = _MyTextsEP._get_choices_from_response(
            _FakeResponse("c")
        )
        assert assistant == "c"
        assert choices == [{"message": {"content": "c"}}]

    def test_ollama_message_fallback(self):
        resp = type(
            "R", (), {"json": lambda self: {"message": {"content": "oll"}}}
        )()
        j, choices, assistant = _MyTextsEP._get_choices_from_response(resp)
        assert assistant == "oll"
        assert choices == [{"message": {"content": "oll"}}]

    def test_no_choices_empty_assistant(self):
        resp = type("R", (), {"json": lambda self: {"foo": 1}})()
        j, choices, assistant = _MyTextsEP._get_choices_from_response(resp)
        assert choices == []
        assert assistant == ""
