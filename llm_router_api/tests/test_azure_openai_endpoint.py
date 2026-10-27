"""
Integration tests for routing OpenAI‑shaped requests to an Azure OpenAI
provider through the real endpoint/dispatch/executor stack (only the
outbound ``requests`` calls and the model resolution are mocked).

Covered:

* non‑streaming chat – deployment URL with the ``api-version`` parameter,
  the OpenAI body with the deployment injected as ``model``, the Azure
  ``api-key`` header, and the pass‑through of the OpenAI‑shaped answer;
* streaming chat – the same URL with the SSE stream forwarded unchanged;
* failover – a 4xx from the first Azure deployment replays the request on
  the second provider;
* embeddings – the deployment embeddings path and the OpenAI list answer.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import requests  # noqa: E402

from llm_router_api.endpoints.builtin.openai import (  # noqa: E402
    OpenAICompletionHandler,
    OpenAIEmbeddingsV1Handler,
)

API_HOST = "https://contoso.openai.azure.com"
DEPLOYMENT = "gpt-4o-2024"


def _azure_provider(provider_id="aoai-1", **overrides):
    base = {
        "id": provider_id,
        "name": "azure/gpt-4o",
        "api_host": API_HOST,
        "api_type": "azure_openai",
        "api_token": "azure-api-key",
        "model_path": DEPLOYMENT,
        "input_size": 128_000,
        "tool_calling": True,
        "is_embedding": False,
        "provider_options": {},
        "fake": False,
        "lease": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _openai_chat_response(text="Hello from Azure", model=DEPLOYMENT):
    return {
        "id": "chatcmpl-azure-1",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 5,
            "completion_tokens": 3,
            "total_tokens": 8,
        },
    }


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


def _make_ep(cls, provider):
    ep = cls(logger_file_name=None, prompt_handler=None, model_handler=None)
    ep._get_router_metrics = lambda: None
    ep.get_model_provider = mock.Mock(return_value=provider)
    return ep


class TestAzureChatNonStreaming:
    def test_end_to_end(self):
        ep = _make_ep(OpenAICompletionHandler, _azure_provider())
        with mock.patch("requests.Session.post") as fake_post:
            fake_post.return_value = _FakeResponse(_openai_chat_response())
            result = ep.run_ep(
                {
                    "model": "azure/gpt-4o",
                    "stream": False,
                    "messages": [{"role": "user", "content": "Hello"}],
                    "temperature": 0.1,
                    "max_tokens": 128,
                }
            )

        # The answer is OpenAI‑shaped: it passes through unconverted.
        assert result["object"] == "chat.completion"
        assert result["choices"][0]["message"]["content"] == "Hello from Azure"

        # URL: the deployment in the path and the mandatory api‑version.
        url = fake_post.call_args.args[0]
        assert url == (
            f"{API_HOST}/openai/deployments/{DEPLOYMENT}/chat/completions"
            "?api-version=2024-10-21"
        )
        # Body: the OpenAI shape, with the deployment injected as model.
        sent = fake_post.call_args.kwargs["json"]
        assert sent["model"] == DEPLOYMENT
        assert sent["messages"] == [{"role": "user", "content": "Hello"}]
        assert sent["stream"] is False
        # Headers: the Azure‑specific api‑key header, no Bearer.
        headers = fake_post.call_args.kwargs["headers"]
        assert headers["api-key"] == "azure-api-key"
        assert "Authorization" not in headers
        assert headers["Content-Type"] == "application/json"

    def test_entra_bearer_header_replaces_the_api_key(self):
        provider = _azure_provider(
            api_token="",
            provider_options={
                "tenant_id": "t",
                "client_id": "c",
                "client_secret": "s",
            },
        )
        ep = _make_ep(OpenAICompletionHandler, provider)
        token_resp = {
            "access_token": "entra-token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

        class _TokenResp:
            status_code = 200
            content = json.dumps(token_resp).encode()

            def json(self):
                return token_resp

        # Two distinct transports are involved and each is stubbed on its own
        # seam: the credential chain posts to the Entra token endpoint with
        # the module-level ``requests.post`` (deliberately not pooled, so the
        # identity probe keeps its fail-fast semantics), while the data plane
        # goes through the pooled ``requests.Session``.
        with (
            mock.patch(
                "llm_router_api.core.api_types.auth.azure.requests.post",
                return_value=_TokenResp(),
            ),
            mock.patch(
                "requests.Session.post",
                return_value=_FakeResponse(_openai_chat_response()),
            ) as fake_post,
        ):
            ep.run_ep(
                {
                    "model": "azure/gpt-4o",
                    "stream": False,
                    "messages": [{"role": "user", "content": "Hello"}],
                }
            )
        headers = fake_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer entra-token"
        assert "api-key" not in headers

    def test_failover_to_next_deployment(self):
        ep = _make_ep(OpenAICompletionHandler, _azure_provider("aoai-1"))
        ep.get_model_provider = mock.Mock(
            side_effect=[
                _azure_provider("aoai-1"),
                _azure_provider(
                    "aoai-2", provider_options={"api_version": "2024-06-01"}
                ),
            ]
        )
        with mock.patch("requests.Session.post") as fake_post:
            fake_post.side_effect = [
                _FakeResponse({"error": {"message": "boom"}}, status_code=500),
                _FakeResponse(_openai_chat_response()),
            ]
            result = ep.run_ep(
                {
                    "model": "azure/gpt-4o",
                    "stream": False,
                    "messages": [{"role": "user", "content": "hi"}],
                }
            )
        assert result["object"] == "chat.completion"
        first_url = fake_post.call_args_list[0].args[0]
        second_url = fake_post.call_args_list[1].args[0]
        assert first_url == second_url.replace(
            "api-version=2024-06-01", "api-version=2024-10-21"
        )


class TestAzureChatStreaming:
    def _sse_bytes(self):
        chunk = {
            "id": "chatcmpl-azure-1",
            "object": "chat.completion.chunk",
            "created": 1_700_000_000,
            "model": DEPLOYMENT,
            "choices": [
                {"index": 0, "delta": {"content": "He"}, "finish_reason": None}
            ],
        }
        last = dict(chunk)
        last["choices"] = [{"index": 0, "delta": {}, "finish_reason": "stop"}]
        return [
            f"data: {json.dumps(chunk)}\n\n".encode(),
            f"data: {json.dumps(last)}\n\n".encode(),
            b"data: [DONE]\n\n",
        ]

    def _fake_stream_response(self):
        chunks = self._sse_bytes()

        class _Resp:
            status_code = 200
            reason = "OK"
            url = "http://test.local"
            text = ""

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def iter_content(self, chunk_size=None):
                return iter(chunks)

        return _Resp()

    def test_stream_end_to_end(self):
        ep = _make_ep(OpenAICompletionHandler, _azure_provider())
        with mock.patch("requests.Session.post") as fake_post:
            fake_post.return_value = self._fake_stream_response()
            stream = ep.run_ep(
                {
                    "model": "azure/gpt-4o",
                    "stream": True,
                    "messages": [{"role": "user", "content": "Hello"}],
                }
            )
            chunks = list(stream)

        url = fake_post.call_args.args[0]
        assert url == (
            f"{API_HOST}/openai/deployments/{DEPLOYMENT}/chat/completions"
            "?api-version=2024-10-21"
        )
        sent = fake_post.call_args.kwargs["json"]
        assert sent["model"] == DEPLOYMENT
        assert sent["stream"] is True
        assert fake_post.call_args.kwargs["headers"]["api-key"] == ("azure-api-key")

        # The Azure SSE stream is the OpenAI stream: forwarded verbatim.
        assert chunks == self._sse_bytes()


class TestAzureEmbeddings:
    def test_end_to_end(self):
        ep = _make_ep(
            OpenAIEmbeddingsV1Handler,
            _azure_provider(
                name="azure/text-embedding-3",
                model_path="embed-3-large",
                is_embedding=True,
            ),
        )
        with mock.patch("requests.Session.post") as fake_post:
            fake_post.return_value = _FakeResponse(
                {
                    "object": "list",
                    "data": [
                        {
                            "object": "embedding",
                            "index": 0,
                            "embedding": [0.1, 0.2, 0.3],
                        }
                    ],
                    "model": "embed-3-large",
                    "usage": {"prompt_tokens": 2, "total_tokens": 2},
                }
            )
            result = ep.run_ep(
                {
                    "model": "azure/text-embedding-3",
                    "input": "hello world",
                }
            )

        url = fake_post.call_args.args[0]
        assert url == (
            f"{API_HOST}/openai/deployments/embed-3-large/embeddings"
            "?api-version=2024-10-21"
        )
        sent = fake_post.call_args.kwargs["json"]
        assert sent["model"] == "embed-3-large"
        assert sent["input"] == "hello world"
        assert result["object"] == "list"
        assert result["data"][0]["embedding"] == [0.1, 0.2, 0.3]
