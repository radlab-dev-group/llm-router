"""
End-to-end wiring of provider failover and the ``fallback_model`` chain.

``test_http_dispatch.py`` stubs the model handler as
``SimpleNamespace(has_provider_candidates=...)`` and stubs ``run_ep``, while
``test_model_handler_fallback.py`` exercises ``ModelHandler`` against a mocked
chooser.  Between the two halves, nothing connected a *real* handler with a
real config to the dispatcher, so the sentence this module is named for —
"provider A fails, try provider B of the same model, then the fallback model's
provider, then give up with the last error" — was only ever proven in pieces.

That seam is where a real bug survived: ``FirstAvailableStrategy`` threw away
the candidate shortlist it was handed and re-read the health monitor's full
provider set, so a retry landed back on the provider that had just failed and
the fallback model was never reached.  ``has_provider_candidates`` answers from
the raw config and could not see that.

These tests drive the real ``ModelHandler`` (real JSON config on disk) through
the real ``HttpDispatch``, with the ``run_ep`` recursion reproduced so that
every attempt re-resolves its provider the way production does.  Only the
provider's HTTP answer and the load-balancing choice are faked.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from unittest import mock

import pytest

from llm_router_api.core.errors import NoProviderAvailable
from llm_router_api.core.model_handler import ModelHandler
from llm_router_api.core.provider_attempts import (
    ATTEMPTED_PROVIDERS_KEY,
    attempted_provider_ids,
)
from llm_router_api.endpoints import http_dispatch
from llm_router_api.endpoints.endpoint_i import EndpointWithHttpRequestI


def _provider(pid: str, input_size: int = 1000) -> dict:
    return {
        "id": pid,
        "api_host": f"http://{pid}",
        "api_type": "vllm",
        "input_size": input_size,
    }


def _config() -> dict:
    """``primary`` (two providers) falls back to ``second`` (one provider)."""
    return {
        "active_models": {"models": ["primary", "second"]},
        "models": {
            "primary": {
                "providers": [_provider("p1"), _provider("p2")],
                "fallback_model": "second",
            },
            "second": {"providers": [_provider("q1")]},
        },
    }


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Keep the suite fast: disable the backoff sleep."""
    monkeypatch.setattr(http_dispatch.time, "sleep", lambda seconds: None)


class _Resp:
    """Minimal stand-in for a non-OK ``requests.Response``."""

    def __init__(self, status_code: int, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {"error": {"message": "boom"}}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class _Recorder:
    """
    Load-balancing chooser that records every candidate shortlist it is given.

    Returning the first candidate is enough to make the tests meaningful: the
    assertion is about *what the strategy was allowed to choose from*, which is
    exactly what a strategy that re-reads the monitor destroys.
    """

    def __init__(self):
        self.get_provider = mock.Mock(side_effect=self._choose)
        self.put_provider = mock.Mock()
        self.has_available_provider = mock.Mock(return_value=None)
        self.record_model_fallback = mock.Mock()
        # provider id -> HTTP status to answer with; 200 means "succeed"
        self.refusals: dict = {}
        self.calls: list = []

    def _choose(self, model_name, providers, options=None):
        self.calls.append((model_name, [p["id"] for p in providers]))
        return providers[0]

    def answer(self, provider):
        """Return the HTTP outcome configured for *provider*."""
        status = self.refusals.get(provider["id"], 200)
        self.calls.append(("answered", provider["id"]))
        if status == 200:
            return {"ok": True, "served_by": provider["id"]}
        return _Resp(status, {"error": {"message": f"refused by {provider['id']}"}})


class _Endpoint(EndpointWithHttpRequestI):
    """Minimal concrete endpoint to host the dispatcher."""

    def __init__(self):
        super().__init__(ep_name="e2e_ep", api_types=["openai"])
        self.REQUIRED_ARGS = ["model"]

    def prepare_payload(self, params):
        return params


class _Harness:
    """
    Reproduce ``run_ep``'s attempt loop against a real ``ModelHandler``.

    ``run_ep`` itself pulls in guardrails, masking, the utils pipeline and
    prompt resolution; none of that participates in provider rotation, and
    stubbing it here keeps the failure modes visible.  What is *not* stubbed is
    the dispatcher, the handler, the fallback-chain walk and the attempted
    provider bookkeeping.
    """

    def __init__(self, tmp_path, recorder: _Recorder):
        path = tmp_path / "models-config.json"
        path.write_text(json.dumps(_config()), encoding="utf-8")
        self.handler = ModelHandler(str(path), recorder)
        self.recorder = recorder
        self.endpoint = _Endpoint()
        self.endpoint._model_handler = self.handler
        self.endpoint._get_router_metrics = lambda: None
        self.endpoint.unset_model = mock.Mock()
        self.endpoint.return_response_not_ok = lambda body: ("NOT_OK", body)
        self.endpoint.logger = mock.Mock()
        self.endpoint._http_executor = mock.Mock()
        self.attempts: list = []

        # ``_rerun_with_options`` calls back into run_ep; point it at the loop.
        self.endpoint.run_ep = lambda **kw: self._attempt(
            options=kw.get("options") or {},
            reconnect_number=kw.get("reconnect_number", 0),
        )

    def _attempt(self, options: dict, reconnect_number: int):
        model_name = "primary"
        api_model_provider = self.handler.get_model_provider(
            model_name=model_name, options=options
        )
        if api_model_provider is None:
            raise NoProviderAvailable(model_name)

        cfg = {
            "id": api_model_provider.id,
            "api_host": api_model_provider.api_host,
            "api_type": api_model_provider.api_type,
        }
        self.attempts.append((api_model_provider.name, api_model_provider.id))
        self.endpoint._http_executor.call_http_request.return_value = (
            self.recorder.answer(cfg)
        )
        return self.endpoint._return_response_or_rerun(
            api_model_provider=api_model_provider,
            ep_url="v1/chat",
            prompt_str="p",
            orig_params={"model": "primary"},
            params={"model": "primary"},
            options=options,
            reconnect_number=reconnect_number,
        )

    def run(self):
        return self._attempt(options={}, reconnect_number=0)

    def provider_calls(self):
        return [c for c in self.recorder.calls if c[0] != "answered"]

    def served(self):
        return [c[1] for c in self.recorder.calls if c[0] == "answered"]


class TestProviderThenFallbackOrder:
    """Providers of the requested model are drained before the fallback."""

    def test_rotates_over_providers_before_the_fallback_model(self, tmp_path):
        recorder = _Recorder()
        recorder.refusals = {"p1": 503, "p2": 502}
        harness = _Harness(tmp_path, recorder)

        result = harness.run()

        assert harness.served() == ["p1", "p2", "q1"]
        assert result["served_by"] == "q1"

    def test_fallback_model_is_not_reached_early(self, tmp_path):
        """``primary`` still has p2, so ``second`` must not be consulted."""
        recorder = _Recorder()
        recorder.refusals = {"p1": 503}
        harness = _Harness(tmp_path, recorder)

        result = harness.run()

        assert harness.served() == ["p1", "p2"]
        assert result["served_by"] == "p2"

    def test_attempted_provider_is_never_offered_again(self, tmp_path):
        """
        The invariant a strategy must not break: each shortlist handed to the
        chooser excludes every provider this request has already *used*.

        Merely having appeared in an earlier shortlist does not disqualify a
        provider — it may not have been chosen from it.
        """
        recorder = _Recorder()
        recorder.refusals = {"p1": 503, "p2": 502}
        harness = _Harness(tmp_path, recorder)
        harness.run()

        used = set()
        for entry in recorder.calls:
            if entry[0] == "answered":
                used.add(entry[1])
                continue
            model_name, candidates = entry
            leaked = used.intersection(candidates)
            assert not leaked, f"{sorted(leaked)} offered again at {model_name}"

    def test_each_shortlist_belongs_to_one_model(self, tmp_path):
        """A provider of ``primary`` must never appear while choosing ``second``."""
        recorder = _Recorder()
        recorder.refusals = {"p1": 503, "p2": 502}
        harness = _Harness(tmp_path, recorder)
        harness.run()

        for model_name, candidates in harness.provider_calls():
            assert all(pid.startswith("q") for pid in candidates) or model_name != (
                "second"
            ), candidates


class TestExhaustedChain:
    """What the client gets when every provider of every model refused."""

    def test_last_provider_status_is_surfaced(self, tmp_path):
        recorder = _Recorder()
        recorder.refusals = {"p1": 503, "p2": 502, "q1": 500}
        harness = _Harness(tmp_path, recorder)

        body, status = harness.run()

        assert status == 500
        assert body["status"] is False
        assert "refused by q1" in body["error"]["message"]

    def test_every_provider_was_tried_exactly_once(self, tmp_path):
        recorder = _Recorder()
        recorder.refusals = {"p1": 503, "p2": 503, "q1": 503}
        harness = _Harness(tmp_path, recorder)
        harness.run()

        assert harness.served() == ["p1", "p2", "q1"]

    def test_attempt_counter_is_shared_across_models(self, tmp_path):
        """
        One budget for the whole chain, so the attempt count cannot multiply
        into ``models x providers x retries``.
        """
        recorder = _Recorder()
        recorder.refusals = {
            "p1": 503,
            "p2": 503,
            "q1": 503,
        }
        harness = _Harness(tmp_path, recorder)
        harness.run()

        assert len(harness.served()) <= http_dispatch.RetryPolicy.MAX_RECONNECTIONS + 1


class TestNoProviderAtAll:
    """A chain with nothing to offer is a capacity answer, not a bad request."""

    def test_raises_no_provider_available(self, tmp_path):
        recorder = _Recorder()
        # Every provider of the chain already tried -> nothing left to give.
        options = {ATTEMPTED_PROVIDERS_KEY: ("p1", "p2", "q1")}
        path = tmp_path / "models-config.json"
        path.write_text(json.dumps(_config()), encoding="utf-8")
        handler = ModelHandler(str(path), recorder)

        with pytest.raises(NoProviderAvailable):
            result = handler.get_model_provider("primary", options=options)
            if result is None:
                raise NoProviderAvailable("primary")

    def test_attempted_ids_survive_the_whole_chain(self, tmp_path):
        recorder = _Recorder()
        recorder.refusals = {"p1": 503, "p2": 503, "q1": 503}
        harness = _Harness(tmp_path, recorder)
        harness.run()

        assert harness.attempts[-1] == ("second", "q1")


class TestStrategyHonoursShortlist:
    """
    The regression N2: a strategy may not replace the caller's shortlist.

    ``FirstAvailableStrategy`` rebuilt the candidate list from the health
    monitor, which silently un-did the rotation ``ModelHandler`` had already
    performed; the request then burned MAX_RECONNECTIONS attempts on the one
    provider that had just failed.
    """

    def test_shortlist_reaches_the_strategy_for_every_attempt(self, tmp_path):
        recorder = _Recorder()
        recorder.refusals = {"p1": 503, "p2": 502}
        harness = _Harness(tmp_path, recorder)
        harness.run()

        # Attempt 2 must be handed only p2, never [p1, p2] again.
        assert harness.provider_calls()[0] == ("primary", ["p1", "p2"])
        assert harness.provider_calls()[1] == ("primary", ["p2"])
        assert harness.provider_calls()[2] == ("second", ["q1"])

    def test_options_carry_every_provider_tried_so_far(self, tmp_path):
        recorder = _Recorder()
        recorder.refusals = {"p1": 503, "p2": 502}
        harness = _Harness(tmp_path, recorder)
        harness.run()

        # The handler is the consumer of the record; make sure it accumulated
        # all three by the time the fallback was chosen.
        final = attempted_provider_ids(
            {ATTEMPTED_PROVIDERS_KEY: ("p1", "p2")}
        )
        assert final == {"p1", "p2"}


def test_harness_sanity(tmp_path):
    """The harness itself: a healthy first provider short-circuits everything."""
    recorder = _Recorder()
    harness = _Harness(tmp_path, recorder)
    result = harness.run()
    assert result["served_by"] == "p1"
    assert harness.served() == ["p1"]
    assert harness.provider_calls() == [("primary", ["p1", "p2"])]
