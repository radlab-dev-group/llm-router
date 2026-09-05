"""
Unit tests for ``llm_router_api.core.metrics_handler.MetricsHandler``.

Covers the process-wide singleton, the Prometheus multiproc directory
preparation, and the guardrail/masker incident counters (no-op path when
Prometheus is disabled; ``.inc()`` dispatch when it is enabled).
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from unittest import mock  # noqa: E402

import pytest  # noqa: E402

import llm_router_api.core.metrics_handler as metrics_handler_module  # noqa: E402
from llm_router_api.core.metrics_handler import MetricsHandler  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Give every test a fresh singleton instance."""
    MetricsHandler._instance = None
    yield
    MetricsHandler._instance = None


class TestSingleton:
    def test_same_instance_returned(self):
        assert MetricsHandler() is MetricsHandler()

    def test_initialized_flag_set(self):
        assert MetricsHandler()._initialized is True


class TestPrometheusMultiprocDir:
    def test_default_dir_path_suffix(self):
        path = MetricsHandler.prometheus_multiproc_dir_path()
        assert path.endswith(
            os.path.join(".llm-router", "metrics", "prometheus", "multiproc")
        )

    def test_prepare_creates_dir_removes_stale_files(self, tmp_path, monkeypatch):
        target = tmp_path / "multiproc"
        target.mkdir()
        (target / "stale.metric").write_text("old")

        monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(target))

        MetricsHandler.prepare_prometheus_multiproc_dir()

        assert target.is_dir()
        assert not (target / "stale.metric").exists()

    def test_prepare_is_idempotent(self, tmp_path, monkeypatch):
        target = tmp_path / "multiproc"
        monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(target))

        MetricsHandler.prepare_prometheus_multiproc_dir()
        MetricsHandler.prepare_prometheus_multiproc_dir()

        assert target.is_dir()


class TestIncidentCounters:
    def test_noop_when_prometheus_disabled(self):
        assert metrics_handler_module.USE_PROMETHEUS is False
        handler = MetricsHandler()
        handler.inc_guardrail_incident()
        handler.inc_masker_incident()
        assert handler._metrics is None

    @pytest.fixture
    def _prometheus_enabled(self):
        fake_metrics = mock.Mock()
        fake_app = mock.Mock()
        fake_app.extensions = {"prometheus_metrics": fake_metrics}
        with (
            mock.patch.object(metrics_handler_module, "USE_PROMETHEUS", True),
            mock.patch.object(metrics_handler_module, "current_app", fake_app),
        ):
            yield fake_metrics

    def test_guardrail_incident_increments(self, _prometheus_enabled):
        MetricsHandler().inc_guardrail_incident()
        _prometheus_enabled.GUARDRAIL_INCIDENTS.inc.assert_called_once()

    def test_masker_incident_increments(self, _prometheus_enabled):
        MetricsHandler().inc_masker_incident()
        _prometheus_enabled.MASKER_INCIDENTS.inc.assert_called_once()

    def test_metrics_cached_after_first_use(self, _prometheus_enabled):
        handler = MetricsHandler()
        handler.inc_guardrail_incident()
        assert handler._metrics is _prometheus_enabled
        handler.inc_guardrail_incident()
        assert _prometheus_enabled.GUARDRAIL_INCIDENTS.inc.call_count == 2
