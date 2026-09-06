"""
Unit tests for ``llm_router_api.core.auth.metrics.AuthMetrics``.

Each test records into a *fresh* ``CollectorRegistry`` (the class accepts a
custom registry), so there are no cross-test or cross-module collisions with
the module-global ``_REGISTRY``.  The no-op path is exercised by flipping
``IS_PROMETHEUS_AVAILABLE`` before construction.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402
from prometheus_client import CollectorRegistry  # noqa: E402

import llm_router_api.core.auth.metrics as auth_metrics_module  # noqa: E402
from llm_router_api.core.auth.metrics import AuthMetrics  # noqa: E402


@pytest.fixture
def registry():
    return CollectorRegistry()


def _value(registry: CollectorRegistry, name: str, labels: dict):
    # Prometheus normalises label values to strings, so stringify the
    # lookup keys to match whatever the recorder passed (e.g. an int).
    string_labels = {k: str(v) for k, v in labels.items()}
    raw = registry.get_sample_value(name, string_labels)
    return 0.0 if raw is None else float(raw)


class TestRegistryWiring:
    def test_prometheus_available_in_test_env(self):
        assert auth_metrics_module.IS_PROMETHEUS_AVAILABLE is True

    def test_custom_registry_is_used(self, registry):
        metrics = AuthMetrics(registry=registry)
        assert metrics._registry is registry

    def test_default_registry_is_module_registry(self):
        metrics = AuthMetrics()
        assert metrics._registry is auth_metrics_module._REGISTRY

    def test_metric_objects_created(self, registry):
        metrics = AuthMetrics(registry=registry)
        assert metrics.TOTAL is not None
        assert metrics.LATENCY is not None
        assert metrics.RATE_LIMIT is not None
        assert metrics.BUDGET is not None


class TestRecordAttempt:
    def test_success_increments_counter(self, registry):
        metrics = AuthMetrics(registry=registry)
        metrics.record_attempt("success", "key-1")
        assert (
            _value(
                registry,
                "auth_attempts_total",
                {"result": "success", "key_id": "key-1"},
            )
            == 1.0
        )

    def test_increments_accumulate(self, registry):
        metrics = AuthMetrics(registry=registry)
        metrics.record_attempt("failure", "key-2")
        metrics.record_attempt("failure", "key-2")
        assert (
            _value(
                registry,
                "auth_attempts_total",
                {"result": "failure", "key_id": "key-2"},
            )
            == 2.0
        )

    def test_default_key_id_is_unknown(self, registry):
        metrics = AuthMetrics(registry=registry)
        metrics.record_attempt("success")
        assert (
            _value(
                registry,
                "auth_attempts_total",
                {"result": "success", "key_id": "unknown"},
            )
            == 1.0
        )

    def test_labels_are_independent_series(self, registry):
        metrics = AuthMetrics(registry=registry)
        metrics.record_attempt("success", "key-a")
        metrics.record_attempt("failure", "key-b")
        assert (
            _value(
                registry,
                "auth_attempts_total",
                {"result": "failure", "key_id": "key-a"},
            )
            == 0.0
        )
        assert (
            _value(
                registry,
                "auth_attempts_total",
                {"result": "failure", "key_id": "key-b"},
            )
            == 1.0
        )


class TestRecordLatency:
    def test_histogram_count_and_sum(self, registry):
        metrics = AuthMetrics(registry=registry)
        metrics.record_latency("extract", 0.25)
        assert (
            _value(registry, "auth_latency_seconds_count", {"step": "extract"})
            == 1.0
        )
        assert (
            _value(registry, "auth_latency_seconds_sum", {"step": "extract"}) == 0.25
        )

    def test_steps_are_independent_series(self, registry):
        metrics = AuthMetrics(registry=registry)
        metrics.record_latency("authenticate", 0.5)
        assert (
            _value(registry, "auth_latency_seconds_count", {"step": "extract"})
            == 0.0
        )
        assert (
            _value(registry, "auth_latency_seconds_count", {"step": "authenticate"})
            == 1.0
        )


class TestRecordRateLimit:
    def test_counter_labels(self, registry):
        metrics = AuthMetrics(registry=registry)
        metrics.record_rate_limit("key-9", "/api/v1/chat")
        assert (
            _value(
                registry,
                "rate_limit_exceeded_total",
                {"key_id": "key-9", "endpoint": "/api/v1/chat"},
            )
            == 1.0
        )

    def test_accumulates_per_label_set(self, registry):
        metrics = AuthMetrics(registry=registry)
        metrics.record_rate_limit("key-9", "/api/v1/chat")
        metrics.record_rate_limit("key-9", "/api/v1/chat")
        metrics.record_rate_limit("key-9", "/api/v1/completions")
        assert (
            _value(
                registry,
                "rate_limit_exceeded_total",
                {"key_id": "key-9", "endpoint": "/api/v1/chat"},
            )
            == 2.0
        )
        assert (
            _value(
                registry,
                "rate_limit_exceeded_total",
                {"key_id": "key-9", "endpoint": "/api/v1/completions"},
            )
            == 1.0
        )


class TestSetBudget:
    def test_gauge_set(self, registry):
        metrics = AuthMetrics(registry=registry)
        metrics.set_budget("key-1", 150, 1000)
        assert (
            _value(
                registry,
                "key_budget_usage_tokens",
                {"key_id": "key-1", "budget_total": 1000},
            )
            == 150.0
        )

    def test_gauge_overwritten(self, registry):
        metrics = AuthMetrics(registry=registry)
        metrics.set_budget("key-1", 150, 1000)
        metrics.set_budget("key-1", 42, 1000)
        assert (
            _value(
                registry,
                "key_budget_usage_tokens",
                {"key_id": "key-1", "budget_total": 1000},
            )
            == 42.0
        )

    def test_budget_totals_are_independent_series(self, registry):
        metrics = AuthMetrics(registry=registry)
        metrics.set_budget("key-1", 10, 100)
        metrics.set_budget("key-1", 20, 200)
        assert (
            _value(
                registry,
                "key_budget_usage_tokens",
                {"key_id": "key-1", "budget_total": 100},
            )
            == 10.0
        )
        assert (
            _value(
                registry,
                "key_budget_usage_tokens",
                {"key_id": "key-1", "budget_total": 200},
            )
            == 20.0
        )


class TestNoOpPath:
    @pytest.fixture(autouse=True)
    def _prometheus_unavailable(self, monkeypatch):
        monkeypatch.setattr(auth_metrics_module, "IS_PROMETHEUS_AVAILABLE", False)
        yield

    def test_registry_is_none(self):
        metrics = AuthMetrics()
        assert metrics._registry is None

    def test_all_recorders_are_noops(self):
        metrics = AuthMetrics()
        # Must not raise even with the registry disabled.
        metrics.record_attempt("success", "key-1")
        metrics.record_latency("extract", 0.1)
        metrics.record_rate_limit("key-1", "/api/v1/chat")
        metrics.set_budget("key-1", 10, 100)
