"""
Integration tests for routing OpenAI‑shaped requests to a Google Vertex AI
provider through the real endpoint/dispatch/executor stack (only the
outbound ``requests`` calls and the model resolution are mocked).

Covered:

* non‑streaming chat – resource URL, Gemini body, Google headers,
  Gemini→OpenAI response conversion;
* streaming chat – ``streamGenerateContent?alt=sse`` URL and the SSE →
  OpenAI chunk conversion;
* failover – a 5xx from the first Vertex provider replays the request on
  the next one;
* embeddings – ``batchEmbedContents`` body and OpenAI list response.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402
import requests  # noqa: E402

from llm_router_api.endpoints.builtin.openai import (  # noqa: E402
    OpenAICompletionHandler,
    OpenAIEmbeddingsV1Handler,
)


def _vertex_provider(provider_id="vertex-1", **overrides):
    base = {
        "id": provider_id,
        "name": "google/gemini-2.5-flash",
        "api_host": "https://europe-central2-aiplatform.googleapis.com",
        "api_type": "vertex_ai",
        "api_token": "ya29.test",
        "model_path": "gemini-2.5-flash",
        "input_size": 1_000_000,
        "tool_calling": True,
        "is_embedding": False,
        "provider_options": {"project": "my-proj", "region": "europe-central2"},
        "fake": False,
        "lease": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _FakeResponse:
    """Minimal ``requests.Response`` stand‑in."""

    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
        self.text = json.dumps(body) if body is not None else ""
        self.reason = "OK" if status_code < 400 else "Error"
        self.url = "http://test.local"

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error", response=self)


def _gemini_response(text="Hello from Vertex"):
    return {
        "candidates": [
            {
                "content": {"role": "model", "parts": [{"text": text}]},
                "finishReason": "STOP",
                "index": 0,
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 5,
            "candidatesTokenCount": 2,
            "totalTokenCount": 7,
        },
        "modelVersion": "gemini-2.5-flash-001",
    }


def _make_ep(cls, provider):
    ep = cls(logger_file_name=None, prompt_handler=None, model_handler=None)
    ep._get_router_metrics = lambda: None
    ep.get_model_provider = mock.Mock(return_value=provider)
    return ep


class TestVertexChatNonStreaming:
    def test_end_to_end(self):
        ep = _make_ep(OpenAICompletionHandler, _vertex_provider())
        with mock.patch(
            "llm_router_api.endpoints.httprequest.requests.post"
        ) as fake_post:
            fake_post.return_value = _FakeResponse(_gemini_response())
            result = ep.run_ep(
                {
                    "model": "google/gemini-2.5-flash",
                    "stream": False,
                    "messages": [{"role": "user", "content": "Hello"}],
                    "temperature": 0.1,
                    "max_tokens": 128,
                }
            )

        body = result
        assert body["object"] == "chat.completion"
        assert body["model"] == "gemini-2.5-flash-001"
        assert body["choices"][0]["message"]["content"] == "Hello from Vertex"
        assert body["choices"][0]["finish_reason"] == "stop"
        assert body["usage"]["total_tokens"] == 7

        # URL: resource path with project/region + generateContent
        url = fake_post.call_args.args[0]
        assert url == (
            "https://europe-central2-aiplatform.googleapis.com"
            "/v1/projects/my-proj/locations/europe-central2"
            "/publishers/google/models/gemini-2.5-flash:generateContent"
        )
        # body: native Gemini shape, no OpenAI keys
        sent = fake_post.call_args.kwargs["json"]
        assert sent["contents"] == [{"role": "user", "parts": [{"text": "Hello"}]}]
        assert sent["generationConfig"] == {
            "temperature": 0.1,
            "maxOutputTokens": 128,
        }
        assert "model" not in sent
        assert "messages" not in sent
        assert "stream" not in sent
        # headers: Bearer token + JSON
        headers = fake_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer ya29.test"
        assert headers["Content-Type"] == "application/json"

    def test_system_prompt_injected_as_system_instruction(self):
        ep = _make_ep(OpenAICompletionHandler, _vertex_provider())
        with mock.patch(
            "llm_router_api.endpoints.httprequest.requests.post"
        ) as fake_post:
            fake_post.return_value = _FakeResponse(_gemini_response())
            ep.run_ep(
                {
                    "model": "google/gemini-2.5-flash",
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": "be terse"},
                        {"role": "user", "content": "hi"},
                    ],
                }
            )
        sent = fake_post.call_args.kwargs["json"]
        assert sent["systemInstruction"] == {"parts": [{"text": "be terse"}]}
        assert [c["role"] for c in sent["contents"]] == ["user"]

    def test_tool_calling_round_trip(self):
        ep = _make_ep(OpenAICompletionHandler, _vertex_provider())
        gemini_body = {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "weather",
                                    "args": {"city": "WAW"},
                                }
                            }
                        ],
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"totalTokenCount": 9},
            "modelVersion": "gemini-2.5-flash-001",
        }
        with mock.patch(
            "llm_router_api.endpoints.httprequest.requests.post"
        ) as fake_post:
            fake_post.return_value = _FakeResponse(gemini_body)
            result = ep.run_ep(
                {
                    "model": "google/gemini-2.5-flash",
                    "stream": False,
                    "messages": [{"role": "user", "content": "weather in WAW?"}],
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "weather",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"city": {"type": "string"}},
                                },
                            },
                        }
                    ],
                }
            )
        sent = fake_post.call_args.kwargs["json"]
        assert sent["tools"][0]["functionDeclarations"][0]["name"] == "weather"
        assert (
            sent["tools"][0]["functionDeclarations"][0]["parameters"]["type"]
            == "OBJECT"
        )
        message = result["choices"][0]["message"]
        assert message["tool_calls"][0]["function"]["name"] == "weather"
        assert '"city": "WAW"' in message["tool_calls"][0]["function"]["arguments"]

    def test_failover_to_next_provider(self):
        ep = _make_ep(
            OpenAICompletionHandler,
            _vertex_provider("vertex-1"),
        )
        ep.get_model_provider = mock.Mock(
            side_effect=[
                _vertex_provider("vertex-1"),
                _vertex_provider("vertex-2"),
            ]
        )
        with mock.patch(
            "llm_router_api.endpoints.httprequest.requests.post"
        ) as fake_post:
            fake_post.side_effect = [
                _FakeResponse({"error": "boom"}, status_code=500),
                _FakeResponse(_gemini_response()),
            ]
            result = ep.run_ep(
                {
                    "model": "google/gemini-2.5-flash",
                    "stream": False,
                    "messages": [{"role": "user", "content": "hi"}],
                }
            )
        assert result["choices"][0]["message"]["content"] == ("Hello from Vertex")
        assert fake_post.call_count == 2


class TestVertexChatStreaming:
    def _sse_lines(self):
        return [
            (
                b"data: "
                + json.dumps(
                    {
                        "candidates": [
                            {
                                "content": {
                                    "role": "model",
                                    "parts": [{"text": "He"}],
                                }
                            }
                        ]
                    }
                ).encode()
            ),
            (
                b"data: "
                + json.dumps(
                    {
                        "candidates": [
                            {
                                "content": {
                                    "role": "model",
                                    "parts": [{"text": "llo"}],
                                },
                                "finishReason": "STOP",
                            }
                        ],
                        "usageMetadata": {
                            "promptTokenCount": 3,
                            "candidatesTokenCount": 2,
                            "totalTokenCount": 5,
                        },
                        "modelVersion": "gemini-2.5-flash-001",
                    }
                ).encode()
            ),
            b"data: [DONE]",
        ]

    def _fake_stream_response(self):
        lines = self._sse_lines()

        class _Resp:
            status_code = 200
            reason = "OK"
            url = "http://test.local"
            text = ""

            def iter_lines(self, decode_unicode=False):
                return iter(lines)

        return _Resp()

    def test_stream_end_to_end(self):
        ep = _make_ep(OpenAICompletionHandler, _vertex_provider())
        with mock.patch(
            "llm_router_api.core.stream_handler.requests.request"
        ) as fake_request:
            fake_request.return_value = self._fake_stream_response()
            stream = ep.run_ep(
                {
                    "model": "google/gemini-2.5-flash",
                    "stream": True,
                    "messages": [{"role": "user", "content": "Hello"}],
                }
            )
            chunks = list(stream)

        # URL: streaming operation
        url = fake_request.call_args.kwargs["url"]
        assert url.endswith(
            "/publishers/google/models/gemini-2.5-flash"
            ":streamGenerateContent?alt=sse"
        )
        # body: native Gemini shape (no `stream` key, no `model` key)
        sent = fake_request.call_args.kwargs["json"]
        assert "stream" not in sent
        assert "model" not in sent
        assert sent["contents"][0]["parts"] == [{"text": "Hello"}]
        # headers
        assert fake_request.call_args.kwargs["headers"]["Authorization"] == (
            "Bearer ya29.test"
        )

        # chunks: OpenAI SSE, role on the first one, [DONE] last
        assert len(chunks) == 3
        first = json.loads(chunks[0].decode().removeprefix("data: "))
        assert first["object"] == "chat.completion.chunk"
        assert first["choices"][0]["delta"]["role"] == "assistant"
        assert first["choices"][0]["delta"]["content"] == "He"
        last_data = json.loads(chunks[1].decode().removeprefix("data: "))
        assert last_data["choices"][0]["delta"]["content"] == "llo"
        assert last_data["choices"][0]["finish_reason"] == "stop"
        assert last_data["usage"]["total_tokens"] == 5
        assert chunks[2] == b"data: [DONE]\n\n"


class TestVertexEmbeddings:
    def test_end_to_end(self):
        ep = _make_ep(
            OpenAIEmbeddingsV1Handler,
            _vertex_provider(
                model_path="text-embedding-004",
                is_embedding=True,
            ),
        )
        with mock.patch(
            "llm_router_api.endpoints.httprequest.requests.post"
        ) as fake_post:
            fake_post.return_value = _FakeResponse(
                {
                    "embeddings": [{"values": [0.1, 0.2, 0.3]}],
                    "usageMetadata": {"totalTokenCount": 2},
                }
            )
            result = ep.run_ep(
                {
                    "model": "google/text-embedding-004",
                    "input": "hello world",
                }
            )

        url = fake_post.call_args.args[0]
        assert url.endswith(
            "/publishers/google/models/text-embedding-004:batchEmbedContents"
        )
        sent = fake_post.call_args.kwargs["json"]
        assert sent["requests"][0]["content"] == {"parts": [{"text": "hello world"}]}
        body = result
        assert body["object"] == "list"
        assert body["data"][0]["embedding"] == [0.1, 0.2, 0.3]
        assert body["usage"]["total_tokens"] == 2
