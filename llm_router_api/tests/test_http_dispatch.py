"""
Unit tests for the extracted HTTP dispatch / retry logic
(:mod:`llm_router_api.endpoints.http_dispatch`).

These tests cover the code path that the Phase‑4 refactor moved out of
``EndpointWithHttpRequestI`` (and the thin delegate kept on the class):

* successful dict response,
* retry on transient status codes (``random_choice`` + ``reconnect_number``),
* provider failover: every 4xx/5xx is replayed on another provider (attempted
  providers are recorded) and only the last error reaches the client,
* retry exhaustion → ``(error_body, status_code)`` with the provider status,
* transport error → retry on next provider / not‑ok when exhausted,
* streaming failover (first chunk probed, error chunk when nothing is left),
* exponential backoff with jitter,
* late‑binding of endpoint collaborators (overrides resolved at call time),
* ``RetryResponse`` backward‑compat alias of ``http_dispatch.RetryPolicy``.

All collaborators are faked — no network, no Flask app, no Prometheus.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402


from llm_router_api.endpoints import http_dispatch  # noqa: E402
from llm_router_api.core.errors import ProviderStreamError  # noqa: E402
from llm_router_api.core.provider_attempts import (
    ATTEMPTED_PROVIDERS_KEY,
)  # noqa: E402
from llm_router_api.core.stream_handler import StreamConversion  # noqa: E402
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


def _handler_with_candidates(available):
    """Stub model handler whose provider-candidate check answers *available*."""
    return SimpleNamespace(has_provider_candidates=mock.Mock(return_value=available))


def _stream(ep, stream_type=StreamConversion.OPENAI, orig_params=None):
    """Call the streaming dispatch the way ``_dispatch_streaming`` does."""
    return ep._http_dispatch.stream_or_rerun(
        api_model_provider=_provider(),
        ep_url="u",
        params={"a": 2},
        options={},
        stream_type=stream_type,
        orig_params=orig_params,
    )


class _FailingStream:
    """Stream iterator that fails like a provider rejecting the request."""

    def __init__(self, status=503, message="Loading model", error_code=None):
        self.error = ProviderStreamError(
            status_code=status, message=message, error_code=error_code
        )

    def __iter__(self):
        return self

    def __next__(self):
        raise self.error


def _failing_stream(status=503, message="Loading model", error_code=None):
    """Stream that fails the way a provider rejects a stream request."""
    return _FailingStream(status=status, message=message, error_code=error_code)


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
        # The failed provider is remembered, so the rerun picks another one.
        assert kw["options"] == {
            ATTEMPTED_PROVIDERS_KEY: ("prov-1",),
            "random_choice": True,
        }

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

    def test_400_rotates_to_another_provider(self):
        """A 400 describes one provider: another one is tried before giving up."""
        ep = _make_ep()
        ep._http_executor.call_http_request.return_value = _Resp(
            400, body={"error": {"message": "bad input"}}
        )
        out = ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 0
        )
        assert out[0] == "RERUN"
        kw = out[1]
        assert kw["options"][ATTEMPTED_PROVIDERS_KEY] == ("prov-1",)
        assert kw["reconnect_number"] == 1

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


class TestProviderFailover:
    """Every 4xx/5xx moves the request to another provider of the model."""

    def test_attempted_provider_recorded_on_transport_error(self):
        ep = _make_ep()
        ep._http_executor.call_http_request.side_effect = ConnectionError("down")
        out = ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 0
        )
        assert out[0] == "RERUN"
        assert out[1]["options"][ATTEMPTED_PROVIDERS_KEY] == ("prov-1",)

    def test_attempted_providers_accumulate_without_mutating_options(self):
        """The second provider sees the first one, and the caller's options stay."""
        ep = _make_ep()
        ep._http_executor.call_http_request.return_value = _Resp(503)
        options = {ATTEMPTED_PROVIDERS_KEY: ("prov-1",)}
        second = SimpleNamespace(name="m1", api_type="openai", id="prov-2")
        out = ep._return_response_or_rerun(
            second, "u", "p", {"o": 1}, {"a": 2}, options, 1
        )
        assert out[1]["options"][ATTEMPTED_PROVIDERS_KEY] == ("prov-1", "prov-2")
        assert options == {ATTEMPTED_PROVIDERS_KEY: ("prov-1",)}

    def test_untried_candidate_available_rotates_the_request(self):
        ep = _make_ep()
        handler = _handler_with_candidates(True)
        ep._model_handler = handler
        ep._http_executor.call_http_request.return_value = _Resp(503)
        out = ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 0
        )
        assert out[0] == "RERUN"
        handler.has_provider_candidates.assert_called_once_with(
            model_name="m1",
            options={ATTEMPTED_PROVIDERS_KEY: ("prov-1",), "random_choice": True},
        )

    def test_no_candidates_left_reports_the_provider_error(self):
        """Model and fallback chain exhausted → the provider status is surfaced."""
        ep = _make_ep()
        ep._model_handler = _handler_with_candidates(False)
        ep._http_executor.call_http_request.return_value = _Resp(
            503, body={"error": {"message": "Loading model"}}
        )
        out = ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 0
        )
        body, status = out
        assert status == 503
        assert "Loading model" in body["error"]["message"]
        ep.run_ep.assert_not_called()

    def test_transport_error_without_candidates_returns_not_ok(self):
        ep = _make_ep()
        ep._model_handler = _handler_with_candidates(False)
        ep._http_executor.call_http_request.side_effect = ConnectionError("down")
        out = ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 0
        )
        assert out[0] == "NOT_OK"
        ep.run_ep.assert_not_called()

    def test_broken_candidate_check_does_not_block_failover(self):
        ep = _make_ep()
        ep._model_handler = SimpleNamespace(
            has_provider_candidates=mock.Mock(side_effect=RuntimeError("no state"))
        )
        ep._http_executor.call_http_request.return_value = _Resp(500)
        out = ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 0
        )
        assert out[0] == "RERUN"

    def test_allow_list_policy_keeps_unknown_4xx_final(self):
        """``RETRY_ON_ANY_ERROR_STATUS = False`` restores the old allow-list."""

        class _StrictPolicy(http_dispatch.RetryPolicy):
            RETRY_ON_ANY_ERROR_STATUS = False

        ep = _make_ep()
        ep.RetryResponse = _StrictPolicy
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

    def test_allow_list_policy_still_retries_listed_status(self):
        class _StrictPolicy(http_dispatch.RetryPolicy):
            RETRY_ON_ANY_ERROR_STATUS = False

        ep = _make_ep()
        ep.RetryResponse = _StrictPolicy
        ep._http_executor.call_http_request.return_value = _Resp(429)
        out = ep._return_response_or_rerun(
            _provider(), "u", "p", {"o": 1}, {"a": 2}, {}, 0
        )
        assert out[0] == "RERUN"


class TestStreamFailover:
    """A stream is replayed while its first chunk is still missing."""

    def test_chunks_are_forwarded_unchanged(self):
        ep = _make_ep()
        ep._http_executor.stream_response.return_value = iter([b"one", b"two"])
        out = _stream(ep)
        assert list(out) == [b"one", b"two"]
        ep.run_ep.assert_not_called()

    def test_empty_stream_is_reported_not_delivered_empty(self):
        """
        A provider that answers 200 and yields nothing used to reach the client
        as an empty 200 — indistinguishable from a successful empty completion.
        """
        ep = _make_ep()
        ep._http_executor.stream_response.return_value = iter([])
        body, status = _stream(ep)
        assert status == 502
        assert body["error"]["code"] == 502
        assert body["status"] is False
        ep.run_ep.assert_not_called()

    def test_provider_error_reruns_the_request(self):
        ep = _make_ep()
        ep._http_executor.stream_response.return_value = _failing_stream()
        out = _stream(ep, orig_params={"o": 1})
        assert out[0] == "RERUN"
        kw = out[1]
        assert kw["params"] == {"o": 1}
        assert kw["reconnect_number"] == 1
        assert kw["options"][ATTEMPTED_PROVIDERS_KEY] == ("prov-1",)
        assert kw["options"]["random_choice"] is True

    def test_error_while_opening_the_stream_reruns_too(self):
        ep = _make_ep()
        ep._http_executor.stream_response.side_effect = ProviderStreamError(
            status_code=503, message="Loading model"
        )
        out = _stream(ep)
        assert out[0] == "RERUN"

    def test_no_candidates_left_reports_the_provider_status(self):
        """
        An exhausted failover used to answer **200** with an SSE chunk that
        merely mentioned an error, while the same failure with ``stream=False``
        answered 503.  Nothing has been written yet, so the stream path must
        honour the provider status exactly like the non-streaming one.
        """
        ep = _make_ep()
        ep._model_handler = _handler_with_candidates(False)
        ep._http_executor.stream_response.return_value = _failing_stream(
            message="Provider error (HTTP 503)"
        )
        rm = mock.Mock()
        ep._get_router_metrics = lambda: rm
        body, status = _stream(ep)
        assert status == 503
        assert body["error"]["code"] == 503
        assert body["error"]["type"] == "api_error"
        assert "HTTP 503" in body["error"]["message"]
        assert body["status"] is False
        ep.run_ep.assert_not_called()
        rm.record_provider_error.assert_called_once_with(
            provider_type="openai", model_name="m1", error_code="503"
        )

    def test_unreachable_provider_reruns_the_request(self):
        """``status_code`` 0 means "never answered" - still replayable."""
        ep = _make_ep()
        ep._http_executor.stream_response.return_value = _failing_stream(
            status=0, message="A connection error occurred"
        )
        out = _stream(ep)
        assert out[0] == "RERUN"
        assert out[1]["options"][ATTEMPTED_PROVIDERS_KEY] == ("prov-1",)

    def test_unreachable_provider_without_candidates_reports_502(self):
        """
        "Never answered" has no HTTP status of its own, so the client gets 502
        rather than a 200 carrying an error text.
        """
        ep = _make_ep()
        ep._model_handler = _handler_with_candidates(False)
        ep._http_executor.stream_response.return_value = _failing_stream(
            status=0, message="A connection error occurred", error_code="timeout"
        )
        rm = mock.Mock()
        ep._get_router_metrics = lambda: rm
        body, status = _stream(ep)
        assert status == 502
        assert body["error"]["code"] == 502
        assert "connection error" in body["error"]["message"].lower()
        rm.record_provider_error.assert_called_once_with(
            provider_type="openai", model_name="m1", error_code="timeout"
        )

    def test_failure_status_does_not_depend_on_the_stream_format(self):
        """
        The error leaves as a JSON body with a status code, so the conversion
        (SSE vs NDJSON) is no longer the client's concern — a refused stream is
        a refused request whichever way the content would have been framed.
        """
        results = []
        for stream_type in (
            StreamConversion.OPENAI,
            StreamConversion.OPENAI_TO_OLLAMA,
        ):
            ep = _make_ep()
            ep._model_handler = _handler_with_candidates(False)
            ep._http_executor.stream_response.return_value = _failing_stream(
                message="boom"
            )
            results.append(_stream(ep, stream_type=stream_type))

        assert results[0] == results[1]
        assert results[0][1] == 503


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
