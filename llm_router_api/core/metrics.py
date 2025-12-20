"""
Metrics module that provides Prometheus integration for a Flask application.
It defines a :class:`PrometheusMetrics` class that registers request count and
latency metrics, and exposes them at the ``/metrics`` endpoint. The implementation
handles optional Prometheus availability and configures a logger for metric
operations.
"""

import time
from typing import Optional

from flask import Flask, request, Response
from rdl_ml_utils.utils.logger import prepare_logger

from llm_router_api.base.constants import USE_PROMETHEUS, REST_API_LOG_LEVEL

IS_PROMETHEUS_AVAILABLE = False
try:
    from prometheus_client import (
        Gauge,
        Counter,
        Histogram,
        generate_latest,
        CONTENT_TYPE_LATEST,
    )

    IS_PROMETHEUS_AVAILABLE = True
except ImportError:
    Gauge = None
    Counter = None
    Histogram = None
    generate_latest = None
    CONTENT_TYPE_LATEST = None
    IS_PROMETHEUS_AVAILABLE = False


if USE_PROMETHEUS and not IS_PROMETHEUS_AVAILABLE:
    raise RuntimeError(
        "Prometheus is not available, check your installation! Install llm-router "
        "with prometheus to enable Prometheus metrics: pip install .[metrics]"
    )


class PrometheusMetrics(object):
    """
    Helper class that registers Prometheus metrics with a Flask app.

    It creates request counters and latency histograms, adds Flask request
    hooks to record metrics, and provides an endpoint to expose them.
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

    def register_metrics_ep(self):
        """
        Register the ``/metrics`` endpoint on the Flask app.

        The endpoint returns the latest Prometheus metrics payload using
        :func:`_metrics_endpoint`.  It is added dynamically when this method
        is called.
        """

        @self.flask_app.route(self.METRICS_EP)
        def prometheus_metrics():
            data, content_type = self._metrics_endpoint()
            return Response(data, mimetype=content_type)

    def _prepare_request_hooks(self):
        """
        Initialise Prometheus metric objects for request counting and latency.

        Creates a :class:`prometheus_client.Counter` named ``http_requests_total``
        and a :class:`prometheus_client.Histogram` named
        ``http_request_duration_seconds``.  These objects are stored on the
        instance for later use by request hooks.
        """
        self._logger.info("[Prometheus] preparing metrics request hooks")

        self.REQUEST_COUNT = Counter(
            "http_requests_total",
            "Total number of HTTP requests",
            ["method", "endpoint", "http_status"],
        )

        self.REQUEST_LATENCY = Histogram(
            "http_request_duration_seconds",
            "Histogram of request latency (seconds)",
            ["method", "endpoint"],
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
        )

        self.REQUEST_IN_PROGRESS = Gauge(
            "http_requests_in_progress",
            "Number of HTTP requests currently being processed.",
        )

        self.REQUEST_EXCEPTIONS = Counter(
            "http_request_exceptions_total",
            "Total number of HTTP requests that resulted in an exception (5xx status).",
            ["method", "endpoint"],
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
        )

        # Number of times the guard‑rail blocked a request
        self.GUARDRAIL_INCIDENTS = Counter(
            "guardrail_incidents_total",
            "Total number of guard‑rail incidents (blocked requests)",
        )

        # Number of times the masker transformed/masked a request
        self.MASKER_INCIDENTS = Counter(
            "masker_incidents_total",
            "Total number of masker incidents (masked requests)",
        )

        # --------------------------------------------------------------------
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
        )

    def _register_request_hooks(self):
        """
        Attach Flask ``before_request`` and ``after_request`` hooks.

        The ``before_request`` hook stores a start timestamp on the request
        object.  The ``after_request`` hook calculates elapsed time, records it
        in the latency histogram, increments the request counter, and returns
        the original response.
        """
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

    @staticmethod
    def _metrics_endpoint():
        """
        Generate the Prometheus metrics payload.

        Returns
        -------
        tuple
            ``(data, content_type)`` where *data* is the byte string produced by
            :func:`prometheus_client.generate_latest` and *content_type* is the
            appropriate MIME type defined by ``CONTENT_TYPE_LATEST``.
        """
        return generate_latest(), CONTENT_TYPE_LATEST
