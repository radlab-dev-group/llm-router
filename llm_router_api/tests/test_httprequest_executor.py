"""
Unit tests for :class:`HttpRequestExecutor`
(``llm_router_api.endpoints.httprequest``).

Covered without network:

* ``_prepare_full_url_ep`` – host/path joining rules;
* ``_provider_request_error`` – sanitised client‑side error;
* ``call_http_request`` – POST and GET paths: model‑name injection,
  bearer token, system‑prompt prepending, URL/timeout wiring;
* transport failures – ``RuntimeError`` with provider id (no URL/IP leak);
* ``stream_response`` – force‑text branch routing and the regular
  ``StreamConversion`` dispatch (mocked ``StreamHandler``);
* ``_call_for_each_user_message`` – guards and per‑user payload splitting.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402
import requests  # noqa: E402

from llm_router_api.core.stream_handler import (  # noqa: E402
    StreamConversion,
)
from llm_router_api.endpoints.endpoint_i import (  # noqa: E402
    EndpointWithHttpRequestI,
)
from llm_router_api.endpoints.httprequest import (  # noqa: E402
    HttpRequestExecutor,
)


class _DummyEndpoint(EndpointWithHttpRequestI):
    """Minimal concrete endpoint to host the executor."""

    def __init__(self, method: str = "POST"):
        super().__init__(ep_name="dummy_ep", api_types=["builtin"], method=method)

    def prepare_payload(self, params):
        return params


def _provider(**overrides):
    base = {
        "name": "model-a",
        "model_path": "path/model-a",
        "api_token": "sekret",
        "id": "prov-1",
        "api_host": "http://host:7000",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestPrepareFullUrlEp:
    @pytest.mark.parametrize(
        ("host", "ep_url", "expected"),
        [
            ("http://h:1", "/v1/chat", "http://h:1/v1/chat"),
            ("http://h:1/", "/v1/chat", "http://h:1/v1/chat"),
            ("http://h:1/", "v1/chat", "http://h:1/v1/chat"),
            ("http://h:1///", "///v1/x", "http://h:1/v1/x"),
            ("http://h:1", "x", "http://h:1/x"),
        ],
    )
    def test_url_joining(self, host, ep_url, expected):
        out = HttpRequestExecutor._prepare_full_url_ep(
            ep_url=ep_url, api_model_provider=_provider(api_host=host)
        )
        assert out == expected


class TestProviderRequestError:
    def test_contains_method_and_provider_id(self):
        exc = requests.RequestException(
            "500 Server Error for url: http://10.9.8.7:8000/v1"
        )
        err = HttpRequestExecutor._provider_request_error("POST", _provider(), exc)
        assert isinstance(err, RuntimeError)
        assert "[POST]" in str(err)
        assert "prov-1" in str(err)

    def test_unknown_provider_fallback(self):
        err = HttpRequestExecutor._provider_request_error(
            "GET", None, requests.RequestException("boom")
        )
        assert "unknown" in str(err)


class TestCallHttpRequestPost:
    def _endpoint(self):
        ep = _DummyEndpoint(method="POST")
        ep.return_http_response = mock.Mock(return_value={"ok": True})
        return ep

    def test_post_success_wiring(self):
        ep = self._endpoint()
        ex = HttpRequestExecutor(ep)
        params = {"messages": [{"role": "user", "content": "x"}]}
        with mock.patch(
            "llm_router_api.endpoints.httprequest.requests.post"
        ) as post:
            post.return_value = SimpleNamespace(ok=True)
            out = ex.call_http_request(
                ep_url="/v1/chat",
                params=params,
                api_model_provider=_provider(),
                prompt_str="SYS",
            )
        assert out == {"ok": True}
        # model name injected from model_path
        assert params["model"] == "path/model-a"
        # system message prepended
        assert params["messages"][0] == {"role": "system", "content": "SYS"}
        # url, timeout, auth header
        call = post.call_args
        assert call.args[0] == "http://host:7000/v1/chat"
        assert call.kwargs["timeout"] == ep.timeout
        assert call.kwargs["headers"]["Authorization"] == "Bearer sekret"
        ep.return_http_response.assert_called_once()

    def test_model_name_falls_back_to_model_name(self):
        ep = self._endpoint()
        ex = HttpRequestExecutor(ep)
        params = {}
        with mock.patch(
            "llm_router_api.endpoints.httprequest.requests.post"
        ) as post:
            post.return_value = SimpleNamespace(ok=True)
            ex.call_http_request(
                ep_url="v1",
                params=params,
                api_model_provider=_provider(model_path=""),
            )
        assert params["model"] == "model-a"

    def test_no_token_no_auth_header(self):
        ep = self._endpoint()
        ex = HttpRequestExecutor(ep)
        with mock.patch(
            "llm_router_api.endpoints.httprequest.requests.post"
        ) as post:
            post.return_value = SimpleNamespace(ok=True)
            ex.call_http_request(
                ep_url="v1",
                params={},
                api_model_provider=_provider(api_token=""),
            )
        headers = post.call_args.kwargs["headers"]
        assert "Authorization" not in headers
        assert headers["Content-Type"] == "application/json"


class TestCallHttpRequestGet:
    def test_get_success_wiring(self):
        ep = _DummyEndpoint(method="GET")
        ep.return_http_response = mock.Mock(return_value={"ok": 2})
        ex = HttpRequestExecutor(ep)
        params = {"a": 1}
        with mock.patch("llm_router_api.endpoints.httprequest.requests.get") as get:
            get.return_value = SimpleNamespace(ok=True)
            out = ex.call_http_request(
                ep_url="v1/x", params=params, api_model_provider=_provider()
            )
        assert out == {"ok": 2}
        call = get.call_args
        assert call.args[0] == "http://host:7000/v1/x"
        assert call.kwargs["params"]["a"] == 1
        assert call.kwargs["headers"]["Authorization"] == "Bearer sekret"


class TestTransportErrors:
    def test_post_failure_raises_sanitized_runtime_error(self):
        ep = _DummyEndpoint(method="POST")
        ex = HttpRequestExecutor(ep)
        with mock.patch(
            "llm_router_api.endpoints.httprequest.requests.post"
        ) as post:
            post.side_effect = requests.RequestException(
                "500 Server Error for url: http://10.9.8.7:8000/v1"
            )
            with pytest.raises(RuntimeError) as excinfo:
                ex.call_http_request(
                    ep_url="v1",
                    params={},
                    api_model_provider=_provider(id="prov-9"),
                )
        msg = str(excinfo.value)
        assert "prov-9" in msg
        # the internal URL must not leak to the client error
        assert "10.9.8.7" not in msg

    def test_get_failure_raises_sanitized_runtime_error(self):
        ep = _DummyEndpoint(method="GET")
        ex = HttpRequestExecutor(ep)
        with mock.patch("llm_router_api.endpoints.httprequest.requests.get") as get:
            get.side_effect = requests.RequestException("boom http://1.2.3.4")
            with pytest.raises(RuntimeError, match="prov-1"):
                ex.call_http_request(
                    ep_url="v1", params={}, api_model_provider=_provider()
                )

    def test_raw_post_path_returns_response_before_normalization(self):
        ep = _DummyEndpoint(method="POST")
        ex = HttpRequestExecutor(ep)
        fake = SimpleNamespace(ok=True)
        with mock.patch(
            "llm_router_api.endpoints.httprequest.requests.post"
        ) as post:
            post.return_value = fake
            out = ex._call_post_with_payload(
                ep_url="u",
                params={},
                return_raw_response=True,
                api_model_provider=_provider(),
            )
        assert out is fake


class TestStreamResponseRouting:
    @pytest.fixture
    def executor_with_mock_stream(self):
        ep = _DummyEndpoint(method="POST")
        ex = HttpRequestExecutor(ep)
        ex._stream_handler = mock.Mock()
        ex._stream_handler.stream_openai.return_value = iter(())
        ex._stream_handler.stream_ollama.return_value = iter(())
        ex._stream_handler.stream_lmstudio.return_value = iter(())
        return ex, ex._stream_handler

    @pytest.mark.parametrize(
        "stream_type",
        [
            StreamConversion.OLLAMA,
            StreamConversion.OPENAI_TO_OLLAMA,
        ],
    )
    def test_force_text_routes_to_stream_ollama(
        self, executor_with_mock_stream, stream_type
    ):
        ex, sh = executor_with_mock_stream
        ex.stream_response(
            ep_url="u",
            params={},
            api_model_provider=_provider(),
            stream_type=stream_type,
            force_text="BLOCKED",
        )
        sh.stream_ollama.assert_called_once()
        kwargs = sh.stream_ollama.call_args.kwargs
        assert kwargs["url"] == ""
        assert kwargs["force_text"] == "BLOCKED"

    @pytest.mark.parametrize(
        "stream_type",
        [
            StreamConversion.OPENAI,
            StreamConversion.OLLAMA_TO_OPENAI,
            StreamConversion.ANTHROPIC_TO_OPENAI,
        ],
    )
    def test_force_text_routes_to_stream_openai(
        self, executor_with_mock_stream, stream_type
    ):
        ex, sh = executor_with_mock_stream
        ex.stream_response(
            ep_url="u",
            params={},
            api_model_provider=_provider(),
            stream_type=stream_type,
            force_text="BLOCKED",
        )
        sh.stream_openai.assert_called_once()

    @pytest.mark.parametrize(
        "stream_type",
        [
            StreamConversion.LMSTUDIO_PASSTHROUGH,
            StreamConversion.OPENAI_TO_LMSTUDIO,
            StreamConversion.OLLAMA_TO_LMSTUDIO,
        ],
    )
    def test_force_text_routes_to_stream_lmstudio(
        self, executor_with_mock_stream, stream_type
    ):
        ex, sh = executor_with_mock_stream
        ex.stream_response(
            ep_url="u",
            params={},
            api_model_provider=_provider(),
            stream_type=stream_type,
            force_text="BLOCKED",
        )
        sh.stream_lmstudio.assert_called_once()

    def test_regular_dispatch_openai_default(self, executor_with_mock_stream):
        ex, sh = executor_with_mock_stream
        ex.stream_response(
            ep_url="v1/chat",
            params={"a": 1},
            api_model_provider=_provider(),
            stream_type=None,
        )
        sh.stream_openai.assert_called_once()
        kwargs = sh.stream_openai.call_args.kwargs
        assert kwargs["url"] == "http://host:7000/v1/chat"
        assert kwargs["method"] == "POST"
        assert kwargs["payload"]["stream"] is True
        assert kwargs["payload"]["model"] == "path/model-a"

    def test_regular_dispatch_ollama(self, executor_with_mock_stream):
        ex, sh = executor_with_mock_stream
        ex.stream_response(
            ep_url="api/chat",
            params={},
            api_model_provider=_provider(),
            stream_type=StreamConversion.OLLAMA,
        )
        sh.stream_ollama.assert_called_once()
        assert (
            sh.stream_ollama.call_args.kwargs["url"] == "http://host:7000/api/chat"
        )


class TestCallForEachUserMessage:
    def _post_endpoint(self):
        ep = _DummyEndpoint(method="POST")
        return ep

    def test_requires_prepare_response_function(self):
        ep = self._post_endpoint()
        assert ep.prepare_response_function is None
        ex = HttpRequestExecutor(ep)
        with pytest.raises(RuntimeError, match="_prepare_response_function"):
            ex._call_for_each_user_message(
                ep_url="u",
                system_message={},
                params={"messages": []},
            )

    def test_not_implemented_for_get(self):
        ep = _DummyEndpoint(method="GET")
        ep._prepare_response_function = lambda *a, **k: None
        ex = HttpRequestExecutor(ep)
        with pytest.raises(RuntimeError, match="not implemented for"):
            ex._call_for_each_user_message(
                ep_url="u",
                system_message={},
                params={"messages": []},
            )

    def test_splits_payloads_per_user_message(self):
        ep = self._post_endpoint()
        ep._prepare_response_function = mock.Mock(return_value={"final": 1})
        ex = HttpRequestExecutor(ep)
        fake_resp = mock.Mock()
        ex._call_post_with_payload = mock.Mock(return_value=fake_resp)

        messages = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ]
        out = ex._call_for_each_user_message(
            ep_url="u",
            system_message={"role": "system", "content": "SYS"},
            params={"model": "m", "messages": messages},
            api_model_provider=_provider(),
        )
        assert out == {"final": 1}
        assert ex._call_post_with_payload.call_count == 2
        first_call = ex._call_post_with_payload.call_args_list[0].kwargs
        assert first_call["params"]["messages"] == [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "q1"},
        ]
        second_call = ex._call_post_with_payload.call_args_list[1].kwargs
        assert second_call["params"]["messages"][1]["content"] == "q2"
        fake_resp.raise_for_status.assert_called()
        ep.prepare_response_function.assert_called_once_with(
            [fake_resp, fake_resp], ["q1", "q2"]
        )
