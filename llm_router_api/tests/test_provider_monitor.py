"""
H‑C regression tests for the provider health‑check
(:class:`llm_router_api.core.monitor.provider_monitor.RedisProviderMonitor`).

Contract (see PLAN_TODO.md, item H‑C):

* a provider is **available only on 2xx/3xx** ping responses — 401/403
  (broken auth) and 404 (wrong endpoint) must **not** keep the provider in
  the active pool;
* the ping path is chosen per ``api_type`` (vLLM ``/health``, Ollama
  ``/api/version``, OpenAI‑compatible ``/v1/models``);
* providers without an ``api_type`` field must not crash the monitor;
* the diagnostic label (``auth_error`` vs ``not_found`` vs ``unreachable``)
  is stored for operator triage.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import fakeredis  # noqa: E402
import pytest  # noqa: E402

from llm_router_api.core.monitor.provider_monitor import (
    RedisProviderMonitor,
)  # noqa: E402


class _FakeResp:
    def __init__(self, status_code: int):
        self.status_code = status_code
        self.text = f"HTTP {status_code}"


def _make_monitor(max_consecutive_failures: int = 1):
    # max_consecutive_failures=1 preserves the legacy single‑shot
    # semantics for the contract tests below; the hysteresis tests use
    # the production default (2) explicitly.
    redis_client = fakeredis.FakeRedis(decode_responses=True)
    monitor = RedisProviderMonitor(
        redis_client=redis_client,
        check_interval=3600,  # tests call _check_and_update_status directly
        logger=mock.Mock(),
        check_timeout=0.1,
        max_consecutive_failures=max_consecutive_failures,
    )
    monitor._stop_event.set()  # do not run the background loop in tests
    monitor._thread.join(timeout=0.2)
    return monitor, redis_client


def _provider(**overrides):
    base = {
        "id": "prov-1",
        "api_host": "http://fake-provider",
        "api_type": "openai",
    }
    base.update(overrides)
    return base


class TestAvailabilityContract:
    def test_200_is_available(self):
        monitor, redis_client = _make_monitor()
        with mock.patch(
            "llm_router_api.core.monitor.provider_monitor.requests.get",
            return_value=_FakeResp(200),
        ) as fake_get:
            monitor._check_and_update_status(_provider(), "availability:m1")
        assert redis_client.hget("availability:m1", "prov-1") == "true"
        # openai-compatible ping path
        url = fake_get.call_args.args[0]
        assert url.endswith("/v1/models")

    def test_401_is_unavailable_auth_error(self):
        monitor, redis_client = _make_monitor()
        with mock.patch(
            "llm_router_api.core.monitor.provider_monitor.requests.get",
            return_value=_FakeResp(401),
        ):
            monitor._check_and_update_status(_provider(), "availability:m1")
        assert redis_client.hget("availability:m1", "prov-1") == "false"
        assert redis_client.hget("availability:reason", "prov-1") == "auth_error"

    def test_403_is_unavailable_auth_error(self):
        monitor, redis_client = _make_monitor()
        with mock.patch(
            "llm_router_api.core.monitor.provider_monitor.requests.get",
            return_value=_FakeResp(403),
        ):
            monitor._check_and_update_status(_provider(), "availability:m1")
        assert redis_client.hget("availability:m1", "prov-1") == "false"
        assert redis_client.hget("availability:reason", "prov-1") == "auth_error"

    def test_404_is_unavailable_not_found(self):
        monitor, redis_client = _make_monitor()
        with mock.patch(
            "llm_router_api.core.monitor.provider_monitor.requests.get",
            return_value=_FakeResp(404),
        ):
            monitor._check_and_update_status(_provider(), "availability:m1")
        assert redis_client.hget("availability:m1", "prov-1") == "false"
        assert redis_client.hget("availability:reason", "prov-1") == "not_found"

    def test_500_is_unavailable_server_error(self):
        monitor, redis_client = _make_monitor()
        with mock.patch(
            "llm_router_api.core.monitor.provider_monitor.requests.get",
            return_value=_FakeResp(500),
        ):
            monitor._check_and_update_status(_provider(), "availability:m1")
        assert redis_client.hget("availability:m1", "prov-1") == "false"
        assert (
            redis_client.hget("availability:reason", "prov-1") == "server_error_500"
        )

    def test_connection_error_is_unreachable(self):
        monitor, redis_client = _make_monitor()
        with mock.patch(
            "llm_router_api.core.monitor.provider_monitor.requests.get",
            side_effect=ConnectionRefusedError("boom"),
        ):
            monitor._check_and_update_status(_provider(), "availability:m1")
        assert redis_client.hget("availability:m1", "prov-1") == "false"
        reason = redis_client.hget("availability:reason", "prov-1")
        assert reason.startswith("unreachable")


class TestActivePool:
    def test_401_provider_excluded_from_active_pool(self):
        monitor, redis_client = _make_monitor()
        with mock.patch(
            "llm_router_api.core.monitor.provider_monitor.requests.get",
            return_value=_FakeResp(401),
        ):
            monitor.add_providers("m1", [_provider(id="bad"), _provider(id="good")])
        with mock.patch(
            "llm_router_api.core.monitor.provider_monitor.requests.get",
            return_value=_FakeResp(200),
        ):
            monitor._check_and_update_status(_provider(id="good"), "availability:m1")
        active = monitor.get_providers("m1", only_active=True)
        assert [p["id"] for p in active] == ["good"]

    def test_200_provider_in_active_pool(self):
        monitor, redis_client = _make_monitor()
        with mock.patch(
            "llm_router_api.core.monitor.provider_monitor.requests.get",
            return_value=_FakeResp(200),
        ):
            # add_providers registers the provider AND runs the immediate
            # health‑check, which marks it available.
            monitor.add_providers("m1", [_provider()])
        active = monitor.get_providers("m1", only_active=True)
        assert [p["id"] for p in active] == ["prov-1"]


class TestPingPaths:
    @pytest.mark.parametrize(
        "api_type, expected_path",
        [
            ("vllm", "/health"),
            ("ollama", "/api/version"),
            ("openai", "/v1/models"),
            ("lmstudio", "/v1/models"),
            ("anthropic", "/v1/models"),
            (None, "/"),
            ("unknown_type", "/"),
        ],
    )
    def test_ping_path_per_api_type(self, api_type, expected_path):
        monitor, redis_client = _make_monitor()
        with mock.patch(
            "llm_router_api.core.monitor.provider_monitor.requests.get",
            return_value=_FakeResp(200),
        ) as fake_get:
            monitor._check_and_update_status(
                _provider(api_type=api_type), "availability:m1"
            )
        url = fake_get.call_args.args[0]
        assert url.endswith(expected_path)

    def test_missing_api_type_does_not_crash(self):
        monitor, redis_client = _make_monitor()
        with mock.patch(
            "llm_router_api.core.monitor.provider_monitor.requests.get",
            return_value=_FakeResp(200),
        ):
            # no "api_type" key at all — must not raise KeyError
            monitor._check_and_update_status(
                {"id": "p1", "api_host": "http://fake"}, "availability:m1"
            )
        assert redis_client.hget("availability:m1", "p1") == "true"

    def test_auth_token_sent_with_ping(self):
        monitor, redis_client = _make_monitor()
        with mock.patch(
            "llm_router_api.core.monitor.provider_monitor.requests.get",
            return_value=_FakeResp(200),
        ) as fake_get:
            monitor._check_and_update_status(
                _provider(api_token="secret-token"), "availability:m1"
            )
        kwargs = fake_get.call_args.kwargs
        assert kwargs["headers"]["Authorization"] == "Bearer secret-token"


class TestFallbackProbePaths:
    """A live server that lacks the api_type‑specific health endpoint
    (e.g. ``vllm`` → ``/health`` 404 on an OpenAI‑compatible box) must
    still be detected as available via the generic fallback probes."""

    def test_404_on_vllm_health_then_fallback_200_is_available(self):
        monitor, redis_client = _make_monitor()

        # /health → 404, /v1/models → 200 (live OpenAI‑compatible host)
        def _fake_get(url, **kwargs):
            if url.endswith("/health"):
                return _FakeResp(404)
            if url.endswith("/v1/models"):
                return _FakeResp(200)
            return _FakeResp(404)

        with mock.patch(
            "llm_router_api.core.monitor.provider_monitor.requests.get",
            side_effect=_fake_get,
        ):
            monitor._check_and_update_status(
                _provider(api_type="vllm"), "availability:m1"
            )
        assert redis_client.hget("availability:m1", "prov-1") == "true"
        assert redis_client.hget("availability:reason", "prov-1") == "ok"

    def test_all_paths_404_stays_not_found(self):
        monitor, redis_client = _make_monitor()
        with mock.patch(
            "llm_router_api.core.monitor.provider_monitor.requests.get",
            return_value=_FakeResp(404),
        ) as fake_get:
            monitor._check_and_update_status(
                _provider(api_type="vllm"), "availability:m1"
            )
        assert redis_client.hget("availability:m1", "prov-1") == "false"
        assert redis_client.hget("availability:reason", "prov-1") == "not_found"
        # primary path probed first, then the 3 fallbacks
        assert fake_get.call_count == 4

    def test_auth_error_does_not_fallback(self):
        monitor, redis_client = _make_monitor()
        with mock.patch(
            "llm_router_api.core.monitor.provider_monitor.requests.get",
            return_value=_FakeResp(401),
        ) as fake_get:
            monitor._check_and_update_status(
                _provider(api_type="vllm"), "availability:m1"
            )
        assert redis_client.hget("availability:m1", "prov-1") == "false"
        assert redis_client.hget("availability:reason", "prov-1") == "auth_error"
        # 401 is a definitive server answer — no extra probes
        assert fake_get.call_count == 1

    def test_connection_error_does_not_fallback(self):
        monitor, redis_client = _make_monitor()
        with mock.patch(
            "llm_router_api.core.monitor.provider_monitor.requests.get",
            side_effect=ConnectionRefusedError("boom"),
        ) as fake_get:
            monitor._check_and_update_status(
                _provider(api_type="vllm"), "availability:m1"
            )
        assert redis_client.hget("availability:m1", "prov-1") == "false"
        reason = redis_client.hget("availability:reason", "prov-1")
        assert reason.startswith("unreachable")
        assert fake_get.call_count == 1

    def test_405_on_primary_triggers_fallback(self):
        monitor, redis_client = _make_monitor()

        def _fake_get(url, **kwargs):
            if url.endswith("/health"):
                return _FakeResp(405)
            if url.endswith("/v1/models"):
                return _FakeResp(200)
            return _FakeResp(404)

        with mock.patch(
            "llm_router_api.core.monitor.provider_monitor.requests.get",
            side_effect=_fake_get,
        ):
            monitor._check_and_update_status(
                _provider(api_type="vllm"), "availability:m1"
            )
        assert redis_client.hget("availability:m1", "prov-1") == "true"


class TestHysteresis:
    """A single failed ping must not kick a live provider out of the
    active pool (the host may merely be busy accepting new connections);
    ``max_consecutive_failures`` failures are required, and one success
    resets the counter immediately."""

    def _check(self, monitor, redis_client, resp_or_exc):
        with mock.patch(
            "llm_router_api.core.monitor.provider_monitor.requests.get",
            return_value=resp_or_exc,
            side_effect=resp_or_exc if isinstance(resp_or_exc, Exception) else None,
        ):
            monitor._check_and_update_status(_provider(), "availability:m1")

    def test_single_failure_keeps_provider_active(self):
        monitor, redis_client = _make_monitor(max_consecutive_failures=2)
        # provider becomes available first
        self._check(monitor, redis_client, _FakeResp(200))
        assert redis_client.hget("availability:m1", "prov-1") == "true"
        # single timeout must NOT drop it (busy host, keep-alive still works)
        self._check(monitor, redis_client, TimeoutError("slow accept"))
        assert redis_client.hget("availability:m1", "prov-1") == "true"
        reason = redis_client.hget("availability:reason", "prov-1")
        assert "transient" in reason

    def test_two_consecutive_failures_mark_down(self):
        monitor, redis_client = _make_monitor(max_consecutive_failures=2)
        self._check(monitor, redis_client, _FakeResp(200))
        self._check(monitor, redis_client, TimeoutError("slow accept"))
        assert redis_client.hget("availability:m1", "prov-1") == "true"
        self._check(monitor, redis_client, TimeoutError("slow accept"))
        assert redis_client.hget("availability:m1", "prov-1") == "false"

    def test_success_resets_failure_counter(self):
        monitor, redis_client = _make_monitor(max_consecutive_failures=2)
        self._check(monitor, redis_client, _FakeResp(200))
        self._check(monitor, redis_client, TimeoutError("slow accept"))
        # recovery — counter reset
        self._check(monitor, redis_client, _FakeResp(200))
        assert redis_client.hget("availability:m1", "prov-1") == "true"
        # one more transient failure must not drop it again
        self._check(monitor, redis_client, TimeoutError("slow accept"))
        assert redis_client.hget("availability:m1", "prov-1") == "true"

    def test_new_provider_first_failure_stays_unavailable(self):
        # fail‑closed: a provider never confirmed healthy is not active
        monitor, redis_client = _make_monitor(max_consecutive_failures=2)
        self._check(monitor, redis_client, _FakeResp(404))
        assert redis_client.hget("availability:m1", "prov-1") is None
        active = monitor.get_providers("m1", only_active=True)
        assert active == []

    def test_configurable_threshold_respected(self):
        monitor, redis_client = _make_monitor(max_consecutive_failures=3)
        self._check(monitor, redis_client, _FakeResp(200))
        for _ in range(2):
            self._check(monitor, redis_client, TimeoutError("slow"))
        assert redis_client.hget("availability:m1", "prov-1") == "true"
        self._check(monitor, redis_client, TimeoutError("slow"))
        assert redis_client.hget("availability:m1", "prov-1") == "false"
