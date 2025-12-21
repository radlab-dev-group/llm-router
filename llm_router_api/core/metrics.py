"""
Metrics module that provides Prometheus integration for a Flask application.
It defines a :class:`PrometheusMetrics` class that registers request count
and latency metrics, and exposes them at the ``/metrics`` endpoint. The
implementation now works in *multiprocess* mode, so the same counter is
aggregated across all Gunicorn workers.

The module also raises a clear error when Prometheus is requested but not
installed.
"""

import os
import time
from typing import Optional

from flask import Flask, request, Response
from rdl_ml_utils.utils.logger import prepare_logger

from llm_router_api.base.constants import USE_PROMETHEUS, REST_API_LOG_LEVEL

# ----------------------------------------------------------------------
# Multiprocess support – must be configured **before**
# any metric objects are created.
# ----------------------------------------------------------------------
IS_PROMETHEUS_AVAILABLE = False
try:
    # Directory where each worker stores its own *.db* files.
    # Rhe path can be changed (e.g. to ./logs/prometheus_multiproc) in
    # your deployment script.
    os.environ.setdefault("PROMETHEUS_MULTIPROC_DIR", "./logs/prometheus_multiproc")

    from llm_router_api.core.metrics_handler import MetricsHandler

    MetricsHandler.prepare_prometheus_multiproc_dir()

    from prometheus_client import (
        CollectorRegistry,
        multiprocess,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )

    # Dedicated registry that will aggregate the per‑process data.
    _REGISTRY = CollectorRegistry()
    multiprocess.MultiProcessCollector(_REGISTRY)

    IS_PROMETHEUS_AVAILABLE = True
except ImportError:
    _REGISTRY = None
    Counter = Gauge = Histogram = generate_latest = CONTENT_TYPE_LATEST = None
    IS_PROMETHEUS_AVAILABLE = False


if USE_PROMETHEUS and not IS_PROMETHEUS_AVAILABLE:
    raise RuntimeError(
        "Prometheus is not available, check your installation! Install llm-router "
        "with prometheus to enable Prometheus metrics: pip install .[metrics]"
    )


class PrometheusMetrics:
    """
    Helper class that registers Prometheus metrics with a Flask app.

    All metric objects are created with the *custom* registry defined above,
    which makes them work correctly when the application runs with multiple
    Gunicorn workers (multiprocess mode).
    """

    METRICS_EP = "/metrics"

    def __init__(
        self,
        app: Flask,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
    ):
        """
        Initialise the :class:`PrometheusMetrics` instance.

        Parameters
        ----------
        app : Flask
            The Flask application to which the metrics hooks will be attached.
        logger_file_name : Optional[str]
            File name for metric‑related logs; if ``None`` logging defaults to
            standard output.
        logger_level : Optional[str]
            Logging level for the metrics logger. Defaults to
            ``REST_API_LOG_LEVEL``.
        """
        if not IS_PROMETHEUS_AVAILABLE:
            raise RuntimeError(
                "Prometheus is not available, check your installation."
            )

        self.flask_app = app
        if not self.flask_app:
            raise RuntimeError("Flask app is required!")

        self._logger = prepare_logger(
            logger_name=__name__,
            logger_file_name=logger_file_name,
            log_level=logger_level,
            use_default_config=True,
        )

        self.REQUEST_COUNT = None
        self.REQUEST_LATENCY = None

        self._prepare_request_hooks()
        self._register_request_hooks()

    # ------------------------------------------------------------------
    # Register the ``/metrics`` endpoint – it uses our custom registry.
    # ------------------------------------------------------------------
    def register_metrics_ep(self):
        """Register the ``/metrics`` endpoint on the Flask app."""

        @self.flask_app.route(self.METRICS_EP)
        def prometheus_metrics():
            data, content_type = self._metrics_endpoint()
            return Response(data, mimetype=content_type)

    # ------------------------------------------------------------------
    # Create all metric objects with the custom registry.
    # ------------------------------------------------------------------
    def _prepare_request_hooks(self):
        """Initialise Prometheus metric objects for request counting and latency."""
        self._logger.info("[Prometheus] preparing metrics request hooks")

        self.REQUEST_COUNT = Counter(
            "http_requests_total",
            "Total number of HTTP requests",
            ["method", "endpoint", "http_status"],
            registry=_REGISTRY,
        )

        self.REQUEST_LATENCY = Histogram(
            "http_request_duration_seconds",
            "Histogram of request latency (seconds)",
            ["method", "endpoint"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
            registry=_REGISTRY,
        )

        self.REQUEST_IN_PROGRESS = Gauge(
            "http_requests_in_progress",
            "Number of HTTP requests currently being processed.",
            registry=_REGISTRY,
        )

        self.REQUEST_EXCEPTIONS = Counter(
            "http_request_exceptions_total",
            "Total number of HTTP requests that resulted in an exception (5xx status).",
            ["method", "endpoint"],
            registry=_REGISTRY,
        )

        self.REQUEST_SIZE = Histogram(
            "http_request_size_bytes",
            "Size of HTTP request bodies in bytes.",
            ["method", "endpoint"],
            buckets=(
                100,
                500,
                1_000,
                5_000,
                10_000,
                50_000,
                100_000,
                500_000,
                1_000_000,
            ),
            registry=_REGISTRY,
        )

        self.GUARDRAIL_INCIDENTS = Counter(
            "guardrail_incidents_total",
            "Total number of guard‑rail incidents (blocked requests)",
            registry=_REGISTRY,
        )

        self.MASKER_INCIDENTS = Counter(
            "masker_incidents_total",
            "Total number of masker incidents (masked requests)",
            registry=_REGISTRY,
        )

        self.RESPONSE_SIZE = Histogram(
            "http_response_size_bytes",
            "Size of HTTP response bodies in bytes.",
            ["method", "endpoint", "http_status"],
            buckets=(
                100,
                500,
                1_000,
                5_000,
                10_000,
                50_000,
                100_000,
                500_000,
                1_000_000,
            ),
            registry=_REGISTRY,
        )

    # ------------------------------------------------------------------
    # Flask request hooks – unchanged logic, only the metric objects
    # are now the multiprocess‑aware ones created above.
    # ------------------------------------------------------------------
    def _register_request_hooks(self):
        """Attach Flask ``before_request`` and ``after_request`` hooks."""

        self._logger.info("[Prometheus] registering metrics request hooks")

        @self.flask_app.before_request
        def _start_timer():
            request.start_time = time.time()
            # Increment in‑progress gauge
            self.REQUEST_IN_PROGRESS.inc()

            # Record request size if a body is present
            if request.content_length:
                self.REQUEST_SIZE.labels(
                    method=request.method,
                    endpoint=request.path,
                ).observe(request.content_length)

        @self.flask_app.after_request
        def _record_metrics(response):
            if hasattr(request, "start_time"):
                elapsed = time.time() - request.start_time
                self.REQUEST_LATENCY.labels(
                    method=request.method,
                    endpoint=request.path,
                ).observe(elapsed)

                # Record response size (Content‑Length header
                # may be missing for streamed responses)
                resp_length = response.calculate_content_length()
                if resp_length is not None:
                    self.RESPONSE_SIZE.labels(
                        method=request.method,
                        endpoint=request.path,
                        http_status=response.status_code,
                    ).observe(resp_length)

                # Decrement in‑progress gauge
                self.REQUEST_IN_PROGRESS.dec()

                # Count exceptions (5xx)
                if 500 <= response.status_code < 600:
                    self.REQUEST_EXCEPTIONS.labels(
                        method=request.method,
                        endpoint=request.path,
                    ).inc()

            self.REQUEST_COUNT.labels(
                method=request.method,
                endpoint=request.path,
                http_status=response.status_code,
            ).inc()
            return response

    # ------------------------------------------------------------------
    # Generate the payload from the *custom* registry.
    # ------------------------------------------------------------------
    @staticmethod
    def _metrics_endpoint():
        """
        Generate the Prometheus metrics payload.

        Returns
        -------
        tuple
            ``(data, content_type)`` where *data* is the byte string produced by
            ``prometheus_client.generate_latest`` and *content_type* is the MIME
            type defined by ``CONTENT_TYPE_LATEST``.
        """
        if not USE_PROMETHEUS:
            return b"", CONTENT_TYPE_LATEST

        return generate_latest(_REGISTRY), CONTENT_TYPE_LATEST
