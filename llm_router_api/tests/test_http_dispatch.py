"""
Unit tests for the extracted HTTP dispatch / retry logic
(:mod:`llm_router_api.endpoints.http_dispatch`).

These tests cover the code path that the Phase‑4 refactor moved out of
``EndpointWithHttpRequestI`` (and the thin delegate kept on the class):

* successful dict response,
* retry on transient status codes (``random_choice`` + ``reconnect_number``),
* retry exhaustion → ``(error_body, status_code)`` with the provider status,
* non‑retryable provider status (e.g. 400) → status surfaced to the client,
* transport error → retry on next provider / not‑ok when exhausted,
* exponential backoff with jitter,
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
from llm_router_api.endpoints.endpoint_i import (
    EndpointWithHttpRequestI,
)  # noqa: E402


class _DummyEndpoint(EndpointWithHttpRequestI):
    """Minimal concrete endpoint used to host the dispatch logic."""

    def __init__(self):
        super().__init__(ep_name="dummy_ep", api_types=["builtin"])
        self.REQUIRED_ARGS = ["x"]

    def prepare_payload(self, params):
        return params


class _Resp:
    def __init__(self, status_code, body=None, text=None):
        self.status_code = status_code
        self._body = body
        self.text = (
            text if text is not None else (str(body) if body is not None else "")
        )

    def json(self):
        if self._body is None:
            raise ValueError("no json body")
        return self._body


def _provider():
    return SimpleNamespace(name="m1", api_type="openai", id="prov-1")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Keep the suite fast: disable the backoff sleep in tests."""
    monkeypatch.setattr(http_dispatch.time, "sleep", lambda seconds: None)


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
        out = ep._return_response_or_rerun(None, "u", "p", {"o": 1}, {"a": 2}, {}, 0)
        assert out == {
            "ok": 1,
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
        }
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
        ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 0
        )
        _, kwargs = ep._http_executor.call_http_request.call_args
        assert kwargs["call_for_each_user_msg"] is True


class TestHttpDispatchRetry:
    def test_429_triggers_retry_with_random_choice(self):
        """429 → rerun on the next provider (random_choice + counter+1)."""
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

    def test_429_then_200_sequence_returns_success(self):
        """Sequence 429 → 200: the client ends up with the successful body."""
        ep = _make_ep()
        # First attempt: 429 (retryable). The re‑issued run_ep (which in
        # production resolves a *different* provider) succeeds with 200.
        ep._http_executor.call_http_request.return_value = _Resp(429)
        ep.run_ep = mock.Mock(return_value={"ok": "recovered"})
        out = ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 0
        )
        assert out == {"ok": "recovered"}
        # The rerun went through run_ep with a fresh provider selection.
        ep.run_ep.assert_called_once()
        _, kw = ep.run_ep.call_args
        assert kw["options"]["random_choice"] is True
        assert kw["reconnect_number"] == 1

    def test_500_exhausted_returns_provider_status(self):
        """500 → 500: after N attempts the client gets the provider's 500."""
        ep = _make_ep()
        ep._http_executor.call_http_request.return_value = _Resp(
            500, body={"error": {"message": "boom from provider"}}
        )
        max_attempts = http_dispatch.RetryPolicy.MAX_RECONNECTIONS
        out = ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, max_attempts
        )
        body, status = out
        assert status == 500
        assert body["status"] is False
        assert body["error"]["code"] == 500
        assert "boom from provider" in body["error"]["message"]
        ep.run_ep.assert_not_called()

    def test_non_retryable_400_not_retried(self):
        ep = _make_ep()
        ep._http_executor.call_http_request.return_value = _Resp(
            400, body={"error": {"message": "bad input"}}
        )
        out = ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 0
        )
        body, status = out
        assert status == 400
        assert body["error"]["message"] == "bad input"
        ep.run_ep.assert_not_called()

    def test_502_is_retryable(self):
        ep = _make_ep()
        ep._http_executor.call_http_request.return_value = _Resp(502)
        out = ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 0
        )
        assert out[0] == "RERUN"


class TestHttpDispatchErrors:
    def test_executor_exception_retries_then_fails(self):
        """Transport error → rerun on another provider while budget remains."""
        ep = _make_ep()
        ep._http_executor.call_http_request.side_effect = RuntimeError("boom")
        out = ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 0
        )
        assert out[0] == "RERUN"
        kw = out[1]
        assert kw["options"]["random_choice"] is True
        assert kw["reconnect_number"] == 1

    def test_executor_exception_exhausted_returns_not_ok(self):
        ep = _make_ep()
        ep._http_executor.call_http_request.side_effect = RuntimeError("boom")
        max_attempts = http_dispatch.RetryPolicy.MAX_RECONNECTIONS
        out = ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, max_attempts
        )
        assert isinstance(out, tuple) and out[0] == "NOT_OK"
        with pytest.raises(RuntimeError):
            raise out[1]

    def test_no_response_returns_not_ok(self):
        ep = _make_ep()
        ep._http_executor.call_http_request.return_value = None
        out = ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 0
        )
        assert isinstance(out, tuple) and out[0] == "NOT_OK"


class TestHttpDispatchMetrics:
    def test_retry_records_metrics(self):
        ep = _make_ep()
        rm = mock.Mock()
        ep._get_router_metrics = lambda: rm
        ep._http_executor.call_http_request.return_value = _Resp(429)
        ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 0
        )
        rm.record_retry.assert_called_once()
        rm.record_provider_error.assert_called()
        rm.record_provider_latency.assert_called()
        rm.record_retry_exhausted.assert_not_called()

    def test_exhausted_records_retry_exhausted(self):
        ep = _make_ep()
        rm = mock.Mock()
        ep._get_router_metrics = lambda: rm
        ep._http_executor.call_http_request.return_value = _Resp(500)
        max_attempts = http_dispatch.RetryPolicy.MAX_RECONNECTIONS
        ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, max_attempts
        )
        rm.record_retry_exhausted.assert_called_once_with(
            model_name="m1", last_error_code="500"
        )

    def test_success_records_usage_tokens(self):
        ep = _make_ep()
        rm = mock.Mock()
        ep._get_router_metrics = lambda: rm
        ep._http_executor.call_http_request.return_value = {
            "ok": 1,
            "usage": {"prompt_tokens": 7, "completion_tokens": 11},
        }
        ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 0
        )
        calls = {
            c.args[0] if c.args else None for c in rm.record_tokens.call_args_list
        }
        assert rm.record_tokens.call_count == 2

    def test_metrics_never_break_request(self):
        ep = _make_ep()
        rm = mock.Mock()
        rm.record_provider_latency.side_effect = RuntimeError("metrics down")
        ep._get_router_metrics = lambda: rm
        ep._http_executor.call_http_request.return_value = _Resp(429)
        out = ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 0
        )
        assert out[0] == "RERUN"  # request path unaffected by metrics failure


class TestBackoffPolicy:
    def test_exponential_backoff_with_cap_and_jitter(self):
        ep = _make_ep()
        base = http_dispatch.RetryPolicy.TIME_TO_WAIT_SEC
        cap = http_dispatch.RetryPolicy.MAX_BACKOFF_SEC
        d0 = ep._http_dispatch._backoff_delay(0)
        d1 = ep._http_dispatch._backoff_delay(1)
        d30 = ep._http_dispatch._backoff_delay(30)
        assert base <= d0 < base * 2  # base * 2**0 + jitter(<base)
        assert 2 * base <= d1 < 2 * base * 2
        assert d30 <= cap + base  # capped
        # monotonic growth until the cap (jitter is bounded by base)
        assert d1 > d0

    def test_policy_constants(self):
        assert 502 in http_dispatch.RetryPolicy.RETRY_WHEN_STATUS
        assert http_dispatch.RetryPolicy.MAX_RECONNECTIONS == 10
        assert http_dispatch.RetryPolicy.MAX_BACKOFF_SEC > 0


class TestHttpDispatchLateBinding:
    def test_overrides_are_resolved_at_call_time(self):
        """
        The original in‑class method resolved ``self.X`` at call time; the
        delegate must preserve that (late‑bound overrides keep working).
        """
        ep = _make_ep()
        sentinel = {"late": "bound"}
        # Rebind *after* construction — must be visible to the dispatch.
        ep._http_executor = mock.Mock()
        ep._http_executor.call_http_request.return_value = sentinel
        out = ep._return_response_or_rerun(None, "u", "p", {"o": 1}, {"a": 2}, {}, 0)
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
            == [429, 500, 502, 503, 504]
        )
        assert (
            EndpointWithHttpRequestI.RetryResponse.TIME_TO_WAIT_SEC
            == http_dispatch.RetryPolicy.TIME_TO_WAIT_SEC
        )
        assert (
            EndpointWithHttpRequestI.RetryResponse.MAX_BACKOFF_SEC
            == http_dispatch.RetryPolicy.MAX_BACKOFF_SEC
        )
        assert issubclass(
            EndpointWithHttpRequestI.RetryResponse, http_dispatch.RetryPolicy
        )
