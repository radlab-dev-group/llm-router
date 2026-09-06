"""
Unit tests for ``llm_router_api.core.metrics.PrometheusMetrics``.

``PrometheusMetrics`` registers its counters/gauges/histograms on the
module-global ``_REGISTRY``, so a *second* construction in the same process
fails with a duplicate-name error.  The fixture below therefore creates a
single ``Flask`` app + ``PrometheusMetrics`` pair per test session and all
tests assert *relative* (delta) metric changes via
``_REGISTRY.get_sample_value``.

``PROMETHEUS_MULTIPROC_DIR`` is pointed at a throwaway directory before the
metrics module is imported, so the multiprocess ``.db`` files never land in
the user's home directory.
"""

from __future__ import annotations

import os
import tempfile

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")
os.environ.setdefault(
    "PROMETHEUS_MULTIPROC_DIR",
    tempfile.mkdtemp(prefix="llm_router_multiproc_"),
)

from unittest import mock  # noqa: E402

import pytest  # noqa: E402
from flask import Flask  # noqa: E402

import llm_router_api.core.metrics as metrics_module  # noqa: E402
from llm_router_api.core.metrics import PrometheusMetrics  # noqa: E402


# ---------------------------------------------------------------------------
# Session-scoped fixtures: exactly ONE PrometheusMetrics per process.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def metrics_app():
    """Flask app with the request hooks of a single PrometheusMetrics."""

    app = Flask("llm_router_api.tests.prometheus_metrics")

    @app.route("/ok")
    def _ok():  # pragma: no cover - simple route
        return "hello-ok"

    @app.route("/err")
    def _err():  # pragma: no cover - simple route
        return "boom", 500

    @app.route("/post", methods=["POST"])
    def _post():  # pragma: no cover - simple route
        return "posted"

    pm = PrometheusMetrics(app=app)
    pm.register_metrics_ep()
    return pm


def _value(name: str, labels: dict):
    """Return the current value of *name*/*labels* (0.0 when absent)."""

    raw = metrics_module._REGISTRY.get_sample_value(name, labels)
    return 0.0 if raw is None else float(raw)


def _delta(call, name: str, labels: dict) -> float:
    """Run *call* and return the metric delta produced by it."""

    before = _value(name, labels)
    call()
    return _value(name, labels) - before


class TestSetup:
    def test_prometheus_available_in_test_env(self):
        assert metrics_module.IS_PROMETHEUS_AVAILABLE is True

    def test_metric_objects_created(self, metrics_app):
        pm = metrics_app
        assert pm.REQUEST_COUNT is not None
        assert pm.REQUEST_LATENCY is not None
        assert pm.REQUEST_IN_PROGRESS is not None
        assert pm.REQUEST_EXCEPTIONS is not None
        assert pm.REQUEST_SIZE is not None
        assert pm.RESPONSE_SIZE is not None
        assert pm.GUARDRAIL_INCIDENTS is not None
        assert pm.MASKER_INCIDENTS is not None

    def test_flask_hooks_registered(self, metrics_app):
        app = metrics_app.flask_app
        assert app.before_request_funcs[None]
        assert app.after_request_funcs[None]

    def test_none_app_rejected(self):
        with pytest.raises(RuntimeError, match="Flask app is required"):
            PrometheusMetrics(app=None)


class TestRequestHooks:
    def test_ok_request_counts_request(self, metrics_app):
        delta = _delta(
            lambda: metrics_app.flask_app.test_client().get("/ok"),
            "http_requests_total",
            {"method": "GET", "endpoint": "/ok", "http_status": "200"},
        )
        assert delta == 1.0

    def test_error_request_counts_5xx(self, metrics_app):
        client = metrics_app.flask_app.test_client()
        request_delta = _delta(
            lambda: client.get("/err"),
            "http_requests_total",
            {"method": "GET", "endpoint": "/err", "http_status": "500"},
        )
        exception_delta = _delta(
            lambda: client.get("/err"),
            "http_request_exceptions_total",
            {"method": "GET", "endpoint": "/err"},
        )
        assert request_delta == 1.0
        assert exception_delta == 1.0

    def test_in_progress_gauge_balances_out(self, metrics_app):
        client = metrics_app.flask_app.test_client()
        before = _value("http_requests_in_progress", {})
        client.get("/ok")
        after = _value("http_requests_in_progress", {})
        assert after == before

    def test_latency_histogram_observed(self, metrics_app):
        client = metrics_app.flask_app.test_client()
        delta = _delta(
            lambda: client.get("/ok"),
            "http_request_duration_seconds_count",
            {"method": "GET", "endpoint": "/ok"},
        )
        assert delta == 1.0

    def test_request_size_observed_for_post_body(self, metrics_app):
        client = metrics_app.flask_app.test_client()
        delta = _delta(
            lambda: client.post("/post", data="x" * 500),
            "http_request_size_bytes_count",
            {"method": "POST", "endpoint": "/post"},
        )
        assert delta == 1.0
        size = _value(
            "http_request_size_bytes_sum", {"method": "POST", "endpoint": "/post"}
        )
        assert size > 0.0

    def test_request_size_not_observed_without_body(self, metrics_app):
        client = metrics_app.flask_app.test_client()
        delta = _delta(
            lambda: client.get("/ok"),
            "http_request_size_bytes_count",
            {"method": "GET", "endpoint": "/ok"},
        )
        assert delta == 0.0

    def test_response_size_observed(self, metrics_app):
        client = metrics_app.flask_app.test_client()
        delta = _delta(
            lambda: client.get("/ok"),
            "http_response_size_bytes_count",
            {"method": "GET", "endpoint": "/ok", "http_status": "200"},
        )
        assert delta == 1.0


class TestIncidentCounters:
    def test_guardrail_incident_counter(self, metrics_app):
        pm = metrics_app
        delta = _delta(pm.GUARDRAIL_INCIDENTS.inc, "guardrail_incidents_total", {})
        assert delta == 1.0

    def test_masker_incident_counter(self, metrics_app):
        pm = metrics_app
        delta = _delta(pm.MASKER_INCIDENTS.inc, "masker_incidents_total", {})
        assert delta == 1.0


class TestMetricsEndpoint:
    def test_endpoint_registered(self, metrics_app):
        rules = {rule.rule for rule in metrics_app.flask_app.url_map.iter_rules()}
        assert PrometheusMetrics.METRICS_EP in rules

    def test_payload_empty_when_use_prometheus_false(self, metrics_app, monkeypatch):
        monkeypatch.setattr(metrics_module, "USE_PROMETHEUS", False)
        resp = metrics_app.flask_app.test_client().get("/metrics")
        assert resp.status_code == 200
        assert resp.data == b""
        assert "text/plain" in resp.headers.get("Content-Type", "")

    def test_payload_generated_when_use_prometheus_true(
        self, metrics_app, monkeypatch
    ):
        monkeypatch.setattr(metrics_module, "USE_PROMETHEUS", True)
        resp = metrics_app.flask_app.test_client().get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("Content-Type", "")
        body = resp.data.decode("utf-8", errors="replace")
        assert body.startswith("#")
        assert "http_requests_total" in body

    def test_metrics_endpoint_delegate(self, metrics_app, monkeypatch):
        """The route calls ``_metrics_endpoint`` and wraps the payload."""

        pm = metrics_app
        payload = b"fake-payload"
        content_type = "text/plain; version=0.0.4"
        with mock.patch.object(
            PrometheusMetrics,
            "_metrics_endpoint",
            staticmethod(
                lambda: (
                    payload,
                    content_type,
                )
            ),
        ):
            resp = pm.flask_app.test_client().get("/metrics")
        assert resp.status_code == 200
        assert resp.data == payload
        assert "version=0.0.4" in resp.headers.get("Content-Type", "")
