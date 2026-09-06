"""
Unit tests for ``llm_router_api.core.monitor.keep_alive.KeepAlive``.

Covers endpoint resolution, provider lookup by ``(model, host)`` and the
``send`` path (HTTP call shape, Authorization header, and graceful
failure when the provider is missing, the API type is unsupported, or
the HTTP call raises).  ``requests.post`` is mocked.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from unittest import mock  # noqa: E402

import pytest  # noqa: E402

from llm_router_api.core.monitor.keep_alive import KeepAlive  # noqa: E402


def _models_configs() -> dict:
    return {
        "model:foo": {
            "providers": [
                {
                    "api_host": "http://h1:8000",
                    "api_type": "vllm",
                    "api_token": "tok",
                    "model_path": "real-foo",
                },
                {
                    "api_host": "http://h2:8000",
                    "api_type": "ollama",
                },
            ]
        }
    }


def _make_keep_alive(models_configs=None) -> KeepAlive:
    if models_configs is None:
        models_configs = _models_configs()
    return KeepAlive(
        models_configs=models_configs,
        logger=mock.Mock(),
        prompt="ping",
        max_tokens=7,
        temperature=0.1,
    )


class TestEndpointFor:
    @pytest.mark.parametrize("api_type", ["vllm", "openai"])
    def test_openai_compatible_endpoint(self, api_type):
        assert (
            KeepAlive._endpoint_for(api_type, "http://h")
            == "http://h/v1/chat/completions"
        )

    def test_ollama_endpoint(self):
        assert KeepAlive._endpoint_for("ollama", "http://h") == "http://h/api/chat"

    def test_endpoint_joins_raw_host(self):
        # _endpoint_for does no normalisation; the trailing-slash trim
        # happens inside send() (see TestSend).
        assert (
            KeepAlive._endpoint_for("vllm", "http://h/")
            == "http://h//v1/chat/completions"
        )

    def test_unknown_api_type_returns_none(self):
        assert KeepAlive._endpoint_for("llama", "http://h") is None


class TestFindProvider:
    def test_model_and_host_match(self):
        keep_alive = _make_keep_alive()
        provider, api_model_name = keep_alive._find_provider("foo", "http://h1:8000")
        assert provider is not None
        assert provider["api_host"] == "http://h1:8000"
        # model_path is used as the API model name when present.
        assert api_model_name == "real-foo"

    def test_model_path_falls_back_to_config_name(self):
        keep_alive = _make_keep_alive()
        provider, api_model_name = keep_alive._find_provider("foo", "http://h2:8000")
        assert provider is not None
        assert api_model_name == "model:foo"

    def test_model_prefix_normalized(self):
        keep_alive = _make_keep_alive()
        provider, _ = keep_alive._find_provider("model:foo", "http://h1:8000")
        assert provider is not None

    def test_no_matching_host(self):
        keep_alive = _make_keep_alive()
        assert keep_alive._find_provider("foo", "http://unknown") == (None, None)

    def test_unknown_model(self):
        keep_alive = _make_keep_alive()
        assert keep_alive._find_provider("nope", "http://h1:8000") == (None, None)


class TestSend:
    def test_post_called_with_endpoint_payload_and_auth(self):
        keep_alive = _make_keep_alive()
        with mock.patch(
            "llm_router_api.core.monitor.keep_alive.requests.post"
        ) as fake_post:
            fake_post.return_value = mock.Mock()
            keep_alive.send("foo", "http://h1:8000")
            fake_post.assert_called_once()
            call = fake_post.call_args
            assert call.args[0] == "http://h1:8000/v1/chat/completions"
            payload = call.kwargs["json"]
            assert payload["model"] == "real-foo"
            assert payload["stream"] is False
            assert payload["messages"] == [{"role": "user", "content": "ping"}]
            assert payload["max_tokens"] == 7
            assert payload["temperature"] == 0.1
            assert call.kwargs["headers"]["Authorization"] == "Bearer tok"
            assert call.kwargs["headers"]["Content-Type"] == "application/json"

    def test_trailing_slash_stripped_in_url(self):
        configs = {
            "m": {"providers": [{"api_host": "http://h/", "api_type": "vllm"}]}
        }
        keep_alive = _make_keep_alive(configs)
        with mock.patch(
            "llm_router_api.core.monitor.keep_alive.requests.post"
        ) as fake_post:
            fake_post.return_value = mock.Mock()
            keep_alive.send("m", "http://h/")
            assert fake_post.call_args.args[0] == "http://h/v1/chat/completions"

    def test_custom_prompt_overrides_default(self):
        keep_alive = _make_keep_alive()
        with mock.patch(
            "llm_router_api.core.monitor.keep_alive.requests.post"
        ) as fake_post:
            fake_post.return_value = mock.Mock()
            keep_alive.send("foo", "http://h1:8000", prompt="custom")
            payload = fake_post.call_args.kwargs["json"]
            assert payload["messages"] == [{"role": "user", "content": "custom"}]

    def test_no_provider_no_http_call(self):
        keep_alive = _make_keep_alive()
        with mock.patch(
            "llm_router_api.core.monitor.keep_alive.requests.post"
        ) as fake_post:
            keep_alive.send("foo", "http://unknown")  # must not raise
            fake_post.assert_not_called()

    def test_unsupported_api_type_no_http_call(self):
        configs = {
            "m": {"providers": [{"api_host": "http://h", "api_type": "llama"}]}
        }
        keep_alive = _make_keep_alive(configs)
        with mock.patch(
            "llm_router_api.core.monitor.keep_alive.requests.post"
        ) as fake_post:
            keep_alive.send("m", "http://h")  # must not raise
            fake_post.assert_not_called()

    def test_http_error_is_swallowed(self):
        keep_alive = _make_keep_alive()
        with mock.patch(
            "llm_router_api.core.monitor.keep_alive.requests.post",
            side_effect=RuntimeError("boom"),
        ):
            keep_alive.send("foo", "http://h1:8000")  # must not raise
