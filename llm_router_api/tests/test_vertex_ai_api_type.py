"""
Unit tests for the Google Vertex AI (Gemini) provider type and converters
(``llm_router_api.core.api_types.vertex_ai``).

Covered: resource path building (project/region/api_version variants),
request headers (api_token / api_key / ADC), OpenAI→Gemini payload
translation (roles, tool results, multimodal parts, sampling params,
tools, provider options), embeddings translation, Gemini→OpenAI
response / stream‑chunk / embedding conversion, and the request‑adapter
hook wiring through :class:`ApiTypesDispatcher`.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402

from llm_router_api.core.api_types.dispatcher import (  # noqa: E402
    ApiTypesDispatcher,
)
from llm_router_api.core.api_types.auth.google import (  # noqa: E402
    GoogleAccessTokenProvider,
)
from llm_router_api.core.api_types.vertex_ai import (  # noqa: E402
    VertexAiConverters,
    VertexAiType,
)


def _provider(**overrides):
    base = {
        "id": "vertex-1",
        "name": "google/gemini-2.5-flash",
        "model_path": "gemini-2.5-flash",
        "api_host": "https://europe-central2-aiplatform.googleapis.com",
        "api_type": "vertex_ai",
        "api_token": "",
        "provider_options": {"project": "my-proj", "region": "europe-central2"},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Endpoint paths
# ---------------------------------------------------------------------------
class TestVertexEndpoints:
    def test_operations(self):
        api = VertexAiType()
        assert api.chat_ep() == ":generateContent"
        assert api.completions_ep() == ":generateContent"
        assert api.responses_ep() == ":generateContent"
        assert api.embeddings_ep() == ":batchEmbedContents"

    def test_chat_path_with_project_and_region(self):
        path = ApiTypesDispatcher.get_proper_endpoint(
            "vertex_ai", "v1/chat/completions", provider=_provider()
        )
        assert path == (
            "/v1/projects/my-proj/locations/europe-central2"
            "/publishers/google/models/gemini-2.5-flash:generateContent"
        )

    def test_stream_path_uses_stream_operation(self):
        path = ApiTypesDispatcher.get_proper_endpoint(
            "vertex_ai",
            "v1/chat/completions",
            provider=_provider(),
            stream=True,
        )
        assert path.endswith(
            "/publishers/google/models/gemini-2.5-flash"
            ":streamGenerateContent?alt=sse"
        )

    def test_embeddings_path(self):
        path = ApiTypesDispatcher.get_proper_endpoint(
            "vertex_ai", "v1/embeddings", provider=_provider()
        )
        assert path.endswith(
            "/publishers/google/models/gemini-2.5-flash:batchEmbedContents"
        )

    def test_api_host_already_carrying_project_prefix(self):
        provider = _provider(
            api_host=(
                "https://us-central1-aiplatform.googleapis.com"
                "/v1/projects/p2/locations/us-central1"
            ),
            provider_options={"project": "p2", "region": "us-central1"},
        )
        path = ApiTypesDispatcher.get_proper_endpoint(
            "vertex_ai", "v1/chat/completions", provider=provider
        )
        # the projects/locations prefix already lives in api_host, so the
        # returned path is the model resource only (no duplication).
        assert path == ("/publishers/google/models/gemini-2.5-flash:generateContent")
        assert "/projects/" not in path

    def test_custom_api_version_and_publisher(self):
        provider = _provider(
            provider_options={
                "project": "p3",
                "region": "europe-west1",
                "api_version": "v1beta",
                "publisher": "amazon",
            }
        )
        path = ApiTypesDispatcher.get_proper_endpoint(
            "vertex_ai", "v1/chat/completions", provider=provider
        )
        assert path.startswith("/v1beta/projects/p3/locations/europe-west1/")
        assert "/publishers/amazon/models/" in path

    def test_model_path_as_full_resource(self):
        provider = _provider(model_path="publishers/google/models/gemini-2.5-flash")
        path = ApiTypesDispatcher.get_proper_endpoint(
            "vertex_ai", "v1/chat/completions", provider=provider
        )
        assert path.endswith(
            "/publishers/google/models/gemini-2.5-flash:generateContent"
        )
        assert "models/gemini-2.5-flash/publishers" not in path

    def test_ping_path_is_resource_only(self):
        path = ApiTypesDispatcher.ping_path("vertex_ai", _provider().__dict__)
        assert path == (
            "/v1/projects/my-proj/locations/europe-central2"
            "/publishers/google/models/gemini-2.5-flash"
        )

    def test_owns_message_normalization(self):
        assert VertexAiType().owns_message_normalization() is True
        assert ApiTypesDispatcher.owns_message_normalization("vertex_ai")
        assert not ApiTypesDispatcher.owns_message_normalization("openai")
        assert not ApiTypesDispatcher.owns_message_normalization("unknown")


# ---------------------------------------------------------------------------
# Request headers
# ---------------------------------------------------------------------------
class TestVertexHeaders:
    def test_api_token_bearer_wins(self):
        headers = ApiTypesDispatcher.request_headers(
            "vertex_ai", _provider(api_token="ya29.x")
        )
        assert headers["Authorization"] == "Bearer ya29.x"
        assert "x-goog-api-key" not in headers

    def test_api_key_header(self):
        headers = ApiTypesDispatcher.request_headers(
            "vertex_ai",
            _provider(
                api_token="",
                provider_options={"project": "p", "region": "r", "api_key": "AIzaX"},
            ),
        )
        assert headers["x-goog-api-key"] == "AIzaX"
        assert "Authorization" not in headers

    def test_adc_token_used_when_no_token(self):
        with mock.patch.object(
            GoogleAccessTokenProvider, "get_token", return_value="adc-token"
        ) as fake:
            headers = ApiTypesDispatcher.request_headers(
                "vertex_ai",
                _provider(provider_options={"project": "p", "region": "r"}),
            )
        assert headers["Authorization"] == "Bearer adc-token"
        fake.assert_called_once_with({"project": "p", "region": "r"})

    def test_adc_failure_surfaces_as_runtime_error(self):
        with mock.patch.object(
            GoogleAccessTokenProvider,
            "get_token",
            side_effect=RuntimeError("google-auth is not installed"),
        ):
            with pytest.raises(RuntimeError, match="google-auth"):
                ApiTypesDispatcher.request_headers("vertex_ai", _provider())


# ---------------------------------------------------------------------------
# Google access token provider (without google-auth installed / mocked)
# ---------------------------------------------------------------------------
class TestGoogleAccessTokenProvider:
    def test_missing_dependency_raises_install_hint(self, monkeypatch):
        import llm_router_api.core.api_types.auth.google as ga

        monkeypatch.setattr(ga, "_GOOGLE_AUTH_AVAILABLE", False)
        with pytest.raises(RuntimeError, match="radlab-llm-router\\[google\\]"):
            GoogleAccessTokenProvider.get_token()

    def test_token_cached_until_refresh_skew(self, monkeypatch):
        import llm_router_api.core.api_types.auth.google as ga

        monkeypatch.setattr(ga, "_GOOGLE_AUTH_AVAILABLE", True)
        GoogleAccessTokenProvider.clear_cache()

        calls = {"n": 0}

        def _fake_build(scopes, credentials_file):
            calls["n"] += 1
            import datetime as _datetime
            import time as _time

            class _Creds:
                token = "tok-1"
                # google-auth exposes ``expiry`` as a datetime
                expiry = _datetime.datetime.fromtimestamp(_time.time() + 3600)

                def refresh(self, request):
                    return None

            return _Creds()

        monkeypatch.setattr(ga, "Request", lambda: None)
        with mock.patch.object(
            ga.GoogleAccessTokenProvider, "_build_credentials", _fake_build
        ):
            first = GoogleAccessTokenProvider.get_token({"project": "p"})
            second = GoogleAccessTokenProvider.get_token({"project": "p"})
        assert first == second == "tok-1"
        assert calls["n"] == 1
        GoogleAccessTokenProvider.clear_cache()


# ---------------------------------------------------------------------------
# OpenAI → Gemini request payload
# ---------------------------------------------------------------------------
class TestVertexPayloadConverter:
    def _convert(self, params, provider=None):
        return ApiTypesDispatcher.request_body(
            "vertex_ai", params, provider or _provider(), None
        )

    def test_system_user_assistant_roles(self):
        body = self._convert(
            {
                "model": "m",
                "messages": [
                    {"role": "system", "content": "be terse"},
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                ],
            }
        )
        assert body["systemInstruction"] == {"parts": [{"text": "be terse"}]}
        assert [c["role"] for c in body["contents"]] == ["user", "model"]
        assert body["contents"][0]["parts"] == [{"text": "hi"}]
        # no OpenAI‑specific keys leak into the body
        assert "model" not in body
        assert "messages" not in body
        assert "stream" not in body

    def test_consecutive_same_role_turns_merged(self):
        body = self._convert(
            {
                "messages": [
                    {"role": "user", "content": "a"},
                    {"role": "tool", "name": "f", "content": "res"},
                ],
            }
        )
        assert [c["role"] for c in body["contents"]] == ["user"]
        parts = body["contents"][0]["parts"]
        assert parts[0] == {"text": "a"}
        assert parts[1]["functionResponse"]["name"] == "f"
        assert parts[1]["functionResponse"]["response"] == {"content": "res"}

    def test_multimodal_content_parts(self):
        body = self._convert(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "describe"},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64,QUJD"},
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": "https://x.test/pic.jpg"},
                            },
                            {"type": "video_url", "video_url": {"url": "x"}},
                        ],
                    }
                ],
            }
        )
        parts = body["contents"][0]["parts"]
        assert parts == [
            {"text": "describe"},
            {"inlineData": {"mimeType": "image/png", "data": "QUJD"}},
            {
                "fileData": {
                    "mimeType": "image/jpeg",
                    "fileUri": "https://x.test/pic.jpg",
                }
            },
        ]

    def test_generation_config_mapping(self):
        body = self._convert(
            {
                "messages": [{"role": "user", "content": "hi"}],
                "temperature": 0.2,
                "top_p": 0.9,
                "max_tokens": 512,
                "stop": "END",
                "response_format": {"type": "json_object"},
                "n": 3,
                "presence_penalty": 0.1,
                "seed": 7,
            }
        )
        assert body["generationConfig"] == {
            "temperature": 0.2,
            "topP": 0.9,
            "maxOutputTokens": 512,
            "stopSequences": ["END"],
            "responseMimeType": "application/json",
        }

    def test_max_tokens_zero_dropped(self):
        body = self._convert(
            {
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 0,
            }
        )
        assert "maxOutputTokens" not in body.get("generationConfig", {})

    def test_stop_string_wrapped_in_list(self):
        body = self._convert(
            {
                "messages": [{"role": "user", "content": "hi"}],
                "stop": ["a", "b"],
            }
        )
        assert body["generationConfig"]["stopSequences"] == ["a", "b"]

    def test_tools_and_tool_choice(self):
        body = self._convert(
            {
                "messages": [{"role": "user", "content": "hi"}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "weather",
                            "description": "weather",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "city": {"type": "string"},
                                    "n": {"type": "integer"},
                                },
                                "required": ["city"],
                            },
                        },
                    }
                ],
                "tool_choice": "required",
            }
        )
        declarations = body["tools"][0]["functionDeclarations"]
        assert declarations[0]["name"] == "weather"
        assert declarations[0]["parameters"]["type"] == "OBJECT"
        assert (
            declarations[0]["parameters"]["properties"]["city"]["type"] == "STRING"
        )
        assert declarations[0]["parameters"]["required"] == ["city"]
        assert body["toolConfig"] == {"functionCallingConfig": {"mode": "ANY"}}

    def test_tool_choice_named_function(self):
        body = self._convert(
            {
                "messages": [{"role": "user", "content": "hi"}],
                "tools": [{"type": "function", "function": {"name": "f"}}],
                "tool_choice": {"type": "function", "function": {"name": "f"}},
            }
        )
        assert body["toolConfig"] == {
            "functionCallingConfig": {
                "mode": "ANY",
                "allowedFunctionNames": ["f"],
            }
        }

    def test_provider_options_overrides(self):
        provider = _provider(
            provider_options={
                "project": "p",
                "region": "r",
                "generation_config": {"maxOutputTokens": 999},
                "safety_settings": [
                    {
                        "category": "HARM_CATEGORY_HARASSMENT",
                        "threshold": "BLOCK_LOW_AND_ABOVE",
                    }
                ],
            }
        )
        body = self._convert(
            {
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 512,
            },
            provider=provider,
        )
        assert body["generationConfig"]["maxOutputTokens"] == 999
        assert body["safetySettings"][0]["category"] == ("HARM_CATEGORY_HARASSMENT")

    def test_system_message_hook_prepended(self):
        body = VertexAiType().request_body(
            {"messages": [{"role": "user", "content": "hi"}]},
            _provider(),
            {"role": "system", "content": "SYS"},
        )
        assert body["systemInstruction"] == {"parts": [{"text": "SYS"}]}


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------
class TestVertexEmbeddings:
    def test_single_string_input(self):
        body = ApiTypesDispatcher.request_body(
            "vertex_ai",
            {"model": "m", "input": "hello"},
            _provider(model_path="text-embedding-004"),
            None,
        )
        assert len(body["requests"]) == 1
        request = body["requests"][0]
        assert request["model"] == "publishers/google/models/text-embedding-004"
        assert request["content"] == {"parts": [{"text": "hello"}]}
        assert "outputDimensionality" not in request

    def test_list_input_with_dimensions(self):
        body = ApiTypesDispatcher.request_body(
            "vertex_ai",
            {"model": "m", "input": ["a", "b"], "dimensions": 768},
            _provider(),
            None,
        )
        assert len(body["requests"]) == 2
        assert body["requests"][0]["outputDimensionality"] == 768

    def test_response_converted_to_openai(self):
        response = {
            "embeddings": [{"values": [0.1, 0.2]}, {"values": [0.3]}],
            "usageMetadata": {"totalTokenCount": 4},
        }
        assert VertexAiConverters.is_gemini_embedding_response(response)
        out = VertexAiConverters.FromGemini.convert_embedding(response)
        assert out["object"] == "list"
        assert out["data"][0] == {
            "object": "embedding",
            "index": 0,
            "embedding": [0.1, 0.2],
        }
        assert out["usage"]["total_tokens"] == 4

    def test_ollama_shape_not_detected_as_gemini(self):
        assert not VertexAiConverters.is_gemini_embedding_response(
            {"embeddings": [[0.1], [0.2]], "model": "m"}
        )


# ---------------------------------------------------------------------------
# Gemini → OpenAI responses
# ---------------------------------------------------------------------------
def _candidate(parts, finish_reason=None):
    candidate = {
        "content": {"role": "model", "parts": parts},
        "index": 0,
    }
    if finish_reason:
        candidate["finishReason"] = finish_reason
    return candidate


class TestVertexResponseConverter:
    def test_text_response(self):
        response = {
            "candidates": [_candidate([{"text": "a"}, {"text": "b"}], "STOP")],
            "usageMetadata": {
                "promptTokenCount": 5,
                "candidatesTokenCount": 2,
                "totalTokenCount": 7,
            },
            "modelVersion": "gemini-2.5-flash-001",
        }
        out = VertexAiConverters.FromGemini.convert_response(response)
        assert out["object"] == "chat.completion"
        assert out["model"] == "gemini-2.5-flash-001"
        message = out["choices"][0]["message"]
        assert message["content"] == "ab"
        assert message["role"] == "assistant"
        assert message["tool_calls"] == []
        assert out["choices"][0]["finish_reason"] == "stop"
        assert out["usage"]["prompt_tokens"] == 5
        assert out["usage"]["completion_tokens"] == 2
        assert out["usage"]["total_tokens"] == 7

    @pytest.mark.parametrize(
        "finish_reason,expected",
        [
            ("MAX_TOKENS", "length"),
            ("SAFETY", "content_filter"),
            ("RECITATION", "content_filter"),
            ("PROHIBITED_CONTENT", "content_filter"),
            ("BLOCKLIST", "content_filter"),
            ("SPII", "content_filter"),
            ("TOOL_CALL", "stop"),
        ],
    )
    def test_finish_reason_mapping(self, finish_reason, expected):
        response = {"candidates": [_candidate([{"text": "x"}], finish_reason)]}
        out = VertexAiConverters.FromGemini.convert_response(response)
        assert out["choices"][0]["finish_reason"] == expected

    def test_function_call_becomes_tool_call(self):
        response = {
            "candidates": [
                _candidate(
                    [
                        {
                            "functionCall": {
                                "name": "weather",
                                "args": {"city": "WAW"},
                            }
                        },
                    ],
                    "STOP",
                )
            ]
        }
        out = VertexAiConverters.FromGemini.convert_response(response)
        message = out["choices"][0]["message"]
        assert message["content"] == ""
        assert len(message["tool_calls"]) == 1
        tool_call = message["tool_calls"][0]
        assert tool_call["type"] == "function"
        assert tool_call["function"]["name"] == "weather"
        assert '"city": "WAW"' in tool_call["function"]["arguments"]
        # no internal helper keys leak
        assert "_index" not in tool_call

    def test_empty_candidates(self):
        out = VertexAiConverters.FromGemini.convert_response({})
        assert out["choices"][0]["message"]["content"] == ""
        assert out["choices"][0]["finish_reason"] == "stop"

    def test_is_gemini_chat_response_markers(self):
        assert VertexAiConverters.is_gemini_chat_response({"candidates": []})
        assert VertexAiConverters.is_gemini_chat_response({"usageMetadata": {}})
        assert not VertexAiConverters.is_gemini_chat_response({"choices": []})


# ---------------------------------------------------------------------------
# Gemini → OpenAI stream chunks
# ---------------------------------------------------------------------------
class TestVertexStreamChunkConverter:
    def test_first_chunk_carries_role(self):
        ctx = VertexAiConverters.FromGemini.new_stream_ctx("m-1")
        chunk = VertexAiConverters.FromGemini.convert_stream_chunk(
            {"candidates": [_candidate([{"text": "Hel"}])]}, ctx
        )
        assert chunk["object"] == "chat.completion.chunk"
        assert chunk["id"].startswith("chatcmpl-vertex-")
        assert chunk["model"] == "m-1"
        delta = chunk["choices"][0]["delta"]
        assert delta["role"] == "assistant"
        assert delta["content"] == "Hel"
        assert chunk["choices"][0]["finish_reason"] is None

    def test_later_chunk_omits_role_and_picks_up_model_version(self):
        ctx = VertexAiConverters.FromGemini.new_stream_ctx("m-1")
        ctx["started"] = True
        chunk = VertexAiConverters.FromGemini.convert_stream_chunk(
            {
                "candidates": [_candidate([{"text": "lo"}], "STOP")],
                "usageMetadata": {
                    "promptTokenCount": 1,
                    "candidatesTokenCount": 1,
                    "totalTokenCount": 2,
                },
                "modelVersion": "gemini-2.5-flash-001",
            },
            ctx,
        )
        delta = chunk["choices"][0]["delta"]
        assert "role" not in delta
        assert delta["content"] == "lo"
        assert chunk["choices"][0]["finish_reason"] == "stop"
        assert chunk["model"] == "gemini-2.5-flash-001"
        assert chunk["usage"]["total_tokens"] == 2

    def test_function_call_delta(self):
        ctx = VertexAiConverters.FromGemini.new_stream_ctx("m-1")
        ctx["started"] = True
        chunk = VertexAiConverters.FromGemini.convert_stream_chunk(
            {
                "candidates": [
                    _candidate([{"functionCall": {"name": "f", "args": {}}}])
                ]
            },
            ctx,
        )
        tool_calls = chunk["choices"][0]["delta"]["tool_calls"]
        assert tool_calls[0]["function"]["name"] == "f"
        assert tool_calls[0]["id"] == "vertex_fc_0"

    def test_usage_only_chunk(self):
        ctx = VertexAiConverters.FromGemini.new_stream_ctx("m-1")
        ctx["started"] = True
        chunk = VertexAiConverters.FromGemini.convert_stream_chunk(
            {"usageMetadata": {"promptTokenCount": 3}}, ctx
        )
        assert chunk["choices"][0]["delta"] == {}
        assert chunk["usage"]["prompt_tokens"] == 3

    def test_empty_chunk_returns_none(self):
        ctx = VertexAiConverters.FromGemini.new_stream_ctx("m-1")
        assert VertexAiConverters.FromGemini.convert_stream_chunk({}, ctx) is None
