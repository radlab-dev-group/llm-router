"""
Unit tests for ``llm_router_api.core.monitor.services_monitor``.

Covers the host ping probe (``_probe_host``), the available-host refresh
logic (``_refresh_available_hosts``) and the lifecycle of the background
thread (``start``/``stop``).  HTTP and the host-registry lookups are
mocked; no network access.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from unittest import mock  # noqa: E402

import pytest  # noqa: E402

from llm_router_api.core.monitor import services_monitor as _sm  # noqa: E402
from llm_router_api.core.monitor.services_monitor import (
    LLMRouterServicesMonitor,
)  # noqa: E402

services_monitor_module = _sm


def _fake_response(status_code: int = 200, body: dict | None = None):
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = body if body is not None else {}
    return response


class TestProbeHost:
    def test_ping_success(self):
        monitor = LLMRouterServicesMonitor()
        with mock.patch(
            "llm_router_api.core.monitor.services_monitor.requests.get",
            return_value=_fake_response(200, {"response": "pong"}),
        ) as fake_get:
            assert monitor._probe_host("http://h") is True
        assert fake_get.call_args.args[0] == "http://h/api/ping"

    def test_ping_success_strips_trailing_slash(self):
        monitor = LLMRouterServicesMonitor()
        with mock.patch(
            "llm_router_api.core.monitor.services_monitor.requests.get",
            return_value=_fake_response(200, {"response": "pong"}),
        ) as fake_get:
            assert monitor._probe_host("http://h/") is True
        assert fake_get.call_args.args[0] == "http://h/api/ping"

    def test_wrong_body_is_unavailable(self):
        monitor = LLMRouterServicesMonitor()
        with mock.patch(
            "llm_router_api.core.monitor.services_monitor.requests.get",
            return_value=_fake_response(200, {"response": "nope"}),
        ):
            assert monitor._probe_host("http://h") is False

    def test_non_200_is_unavailable(self):
        monitor = LLMRouterServicesMonitor()
        with mock.patch(
            "llm_router_api.core.monitor.services_monitor.requests.get",
            return_value=_fake_response(404, {"response": "pong"}),
        ):
            assert monitor._probe_host("http://h") is False

    def test_exception_is_unavailable(self):
        monitor = LLMRouterServicesMonitor()
        with mock.patch(
            "llm_router_api.core.monitor.services_monitor.requests.get",
            side_effect=ConnectionRefusedError("boom"),
        ):
            assert monitor._probe_host("http://h") is False


class TestRefreshAvailableHosts:
    @pytest.fixture
    def monitor_with_strategies(self, monkeypatch):
        monitor = LLMRouterServicesMonitor()
        monitor._all_strategies = ["strategy-a", "strategy-b", "fast_masker"]
        monkeypatch.setattr(
            services_monitor_module,
            "GUARDRAILS_HOSTS_DEFINITION",
            {"strategy-a": "http://guard"},
        )
        monkeypatch.setattr(
            services_monitor_module,
            "MASKERS_HOSTS_DEFINITION",
            {"strategy-b": "http://masker"},
        )
        return monitor

    def test_available_hosts_collected(self, monitor_with_strategies):
        with mock.patch.object(
            LLMRouterServicesMonitor,
            "_probe_host",
            side_effect=lambda host: host == "http://guard",
        ):
            monitor_with_strategies._refresh_available_hosts()
        assert monitor_with_strategies.available_hosts == {
            "strategy-a": "http://guard"
        }

    def test_excluded_plugin_never_probed(self, monitor_with_strategies):
        probe = mock.Mock(return_value=True)
        with mock.patch.object(LLMRouterServicesMonitor, "_probe_host", probe):
            monitor_with_strategies._refresh_available_hosts()
        assert "fast_masker" not in monitor_with_strategies.available_hosts
        probed_hosts = [call.args[0] for call in probe.call_args_list]
        assert probed_hosts == ["http://guard", "http://masker"]

    def test_strategy_without_host_skipped(self, monitor_with_strategies):
        monitor_with_strategies._all_strategies = ["unknown-strategy"]
        with mock.patch.object(LLMRouterServicesMonitor, "_probe_host") as probe:
            monitor_with_strategies._refresh_available_hosts()
            probe.assert_not_called()
        assert monitor_with_strategies.available_hosts == {}


class TestLifecycle:
    def test_constructor_state(self):
        monitor = LLMRouterServicesMonitor()
        assert monitor.available_hosts == {}
        assert not monitor._thread.is_alive()

    def test_all_strategies_is_sum_of_pipelines(self):
        monitor = LLMRouterServicesMonitor()
        assert monitor._all_strategies == (
            monitor._guard_req_strategies
            + monitor._guard_resp_strategies
            + monitor._maskers_strategies
        )

    def test_start_without_strategies_does_not_start_thread(self):
        monitor = LLMRouterServicesMonitor()
        monitor.start()
        assert not monitor._thread.is_alive()

    def test_stop_is_idempotent(self):
        monitor = LLMRouterServicesMonitor()
        monitor.stop()
        monitor.stop()
        assert not monitor._thread.is_alive()
