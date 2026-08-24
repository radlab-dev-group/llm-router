"""
Unit tests for the extracted HTTP dispatch / retry logic
(:mod:`llm_router_api.endpoints.http_dispatch`).

These tests cover the code path that the Phase‑4 refactor moved out of
``EndpointWithHttpRequestI`` (and the thin delegate kept on the class):

* successful dict response,
* retry on transient status codes (``random_choice`` + ``reconnect_number``),
* retry exhaustion,
* executor exception → ``return_response_not_ok``,
* late‑binding of endpoint collaborators (overrides resolved at call time),
* ``RetryResponse`` backward‑compat alias of ``http_dispatch.RetryPolicy``.

All collaborators are faked — no network, no Flask app, no Prometheus.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402

from llm_router_api.endpoints import http_dispatch  # noqa: E402
from llm_router_api.endpoints.endpoint_i import EndpointWithHttpRequestI  # noqa: E402


class _DummyEndpoint(EndpointWithHttpRequestI):
    """Minimal concrete endpoint used to host the dispatch logic."""

    def __init__(self):
        super().__init__(ep_name="dummy_ep", api_types=["builtin"])
        self.REQUIRED_ARGS = ["x"]

    def prepare_payload(self, params):
        return params


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code


def _provider():
    return SimpleNamespace(name="m1", api_type="openai", id="prov-1")


def _make_ep():
    ep = _DummyEndpoint()
    # Deterministic no‑op collaborators (metrics disabled in this environment).
    ep._get_router_metrics = lambda: None
    ep.unset_model = mock.Mock()
    ep.return_response_not_ok = lambda body: ("NOT_OK", body)
    ep.run_ep = mock.Mock(side_effect=lambda **kw: ("RERUN", kw))
    ep._http_executor = mock.Mock()
    return ep


class TestHttpDispatchSuccess:
    def test_dict_response_returned_and_unset_model_called(self):
        ep = _make_ep()
        ep._http_executor.call_http_request.return_value = {
            "ok": 1,
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
        }
        out = ep._return_response_or_rerun(
            None, "u", "p", {"o": 1}, {"a": 2}, {}, 0
        )
        assert out == {"ok": 1, "usage": {"prompt_tokens": 3, "completion_tokens": 4}}
        ep._http_executor.call_http_request.assert_called_once_with(
            ep_url="u",
            params={"a": 2},
            prompt_str="p",
            api_model_provider=None,
            call_for_each_user_msg=False,
        )
        ep.unset_model.assert_called_once_with(
            api_model_provider=None, params={"a": 2}, options={}
        )

    def test_call_for_each_user_msg_flag_forwarded(self):
        ep = _make_ep()
        ep._call_for_each_user_msg = True
        ep._http_executor.call_http_request.return_value = {"ok": 1}
        ep._return_response_or_rerun(_provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 0)
        _, kwargs = ep._http_executor.call_http_request.call_args
        assert kwargs["call_for_each_user_msg"] is True


class TestHttpDispatchRetry:
    def test_retry_status_calls_run_ep_with_random_choice(self):
        ep = _make_ep()
        ep._http_executor.call_http_request.return_value = _Resp(429)
        out = ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 3
        )
        assert out[0] == "RERUN"
        kw = out[1]
        assert kw["params"] == {"o": 1}  # orig_params are used for the rerun
        assert kw["reconnect_number"] == 4
        assert kw["options"] == {"random_choice": True}

    def test_retry_exhausted_returns_raw_response(self):
        ep = _make_ep()
        ep._http_executor.call_http_request.return_value = _Resp(503)
        out = ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 10
        )
        assert isinstance(out, _Resp)
        assert out.status_code == 503
        ep.run_ep.assert_not_called()


class TestHttpDispatchErrors:
    def test_executor_exception_returns_not_ok(self):
        ep = _make_ep()
        ep._http_executor.call_http_request.side_effect = RuntimeError("boom")
        out = ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 0
        )
        assert isinstance(out, tuple) and out[0] == "NOT_OK"
        with pytest.raises(RuntimeError):
            raise out[1]


class TestHttpDispatchLateBinding:
    def test_overrides_are_resolved_at_call_time(self):
        """
        The original in‑class method resolved ``self.X`` at call time; the
        delegate must preserve that (late‑bound overrides keep working).
        """
        ep = _make_ep()
        sentinel = _Resp(200)
        # Rebind *after* construction — must be visible to the dispatch.
        ep._http_executor = mock.Mock()
        ep._http_executor.call_http_request.return_value = sentinel
        out = ep._return_response_or_rerun(
            None, "u", "p", {"o": 1}, {"a": 2}, {}, 0
        )
        assert out is sentinel


class TestRetryResponseAlias:
    def test_alias_matches_policy_constants(self):
        assert (
            EndpointWithHttpRequestI.RetryResponse.MAX_RECONNECTIONS
            == http_dispatch.RetryPolicy.MAX_RECONNECTIONS
            == 10
        )
        assert (
            EndpointWithHttpRequestI.RetryResponse.RETRY_WHEN_STATUS
            == http_dispatch.RetryPolicy.RETRY_WHEN_STATUS
            == [429, 503, 504, 500]
        )
        assert (
            EndpointWithHttpRequestI.RetryResponse.TIME_TO_WAIT_SEC
            == http_dispatch.RetryPolicy.TIME_TO_WAIT_SEC
        )
        assert issubclass(
            EndpointWithHttpRequestI.RetryResponse, http_dispatch.RetryPolicy
        )
