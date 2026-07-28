"""
Prometheus metrics for the LLM router core (routing, provider lifecycle, pipeline).

These metrics are registered alongside the existing HTTP and auth metrics when
Prometheus is enabled (``LLM_ROUTER_USE_PROMETHEUS=true``).

Metrics are grouped into four categories:

A. Routing & Provider ------------------
    * ``llm_router_provider_calls_total``  – calls per provider type / model
    * ``llm_router_provider_latency_seconds``  – latency histogram per provider
    * ``llm_router_provider_error_total``  – errors per provider / error code
    * ``llm_router_lb_strategy_selected_total``  – LB strategy selection counts

B. Pipeline / Request Funnel -----------
    * ``llm_router_pipeline_stage_total``  – stage completion counts
    * ``llm_router_retry_total``  – retry attempts per model / error code
    * ``llm_router_retry_exhausted_total``  – exhausted retries (final failure)

C. Token Usage -------------------------
    * ``llm_router_tokens_total``  – token usage (input/output) per model

D. Streaming & Response Format ---------
    * ``llm_router_response_format_total``  – streamed vs non-streamed counts
    * ``llm_router_payload_conversion_total``  – payload conversion counts
"""

from __future__ import annotations

import os

from llm_router_api.core.metrics_handler import MetricsHandler

# ------------------------------------------------------------------
# Multiprocess support — same pattern as metrics.py and auth/metrics.py
# ------------------------------------------------------------------
IS_PROMETHEUS_AVAILABLE = False
try:
    os.environ.setdefault(
        "PROMETHEUS_MULTIPROC_DIR",
        MetricsHandler.prometheus_multiproc_dir_path(),
    )
    MetricsHandler.prepare_prometheus_multiproc_dir()

    from prometheus_client import (
        CollectorRegistry,
        multiprocess,
        Counter,
        Histogram,
    )

    _REGISTRY = CollectorRegistry()
    multiprocess.MultiProcessCollector(_REGISTRY)

    IS_PROMETHEUS_AVAILABLE = True
except ImportError:
    IS_PROMETHEUS_AVAILABLE = False


class RouterMetrics:
    """
    Prometheus metrics for the LLM router core.

    All methods are no‑ops when Prometheus is not available or not enabled,
    so callers can invoke them unconditionally without guarding every call.
    """

    def __init__(self, registry=None) -> None:
        if not IS_PROMETHEUS_AVAILABLE:
            self._registry = None
            return

        self._registry = registry or _REGISTRY

        # ------------------------------------------------------------------
        # A. Routing & Provider
        # ------------------------------------------------------------------
        self.PROVIDER_CALLS = Counter(
            "llm_router_provider_calls_total",
            "Total number of calls to each provider type",
            ["provider_type", "model_name"],
            registry=self._registry,
        )

        self.PROVIDER_LATENCY = Histogram(
            "llm_router_provider_latency_seconds",
            "Latency of outbound provider calls (seconds)",
            ["provider_type", "model_name"],
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
            registry=self._registry,
        )

        self.PROVIDER_ERROR = Counter(
            "llm_router_provider_error_total",
            "Total provider errors by type and error code",
            ["provider_type", "model_name", "error_code"],
            registry=self._registry,
        )

        self.LB_STRATEGY_SELECTED = Counter(
            "llm_router_lb_strategy_selected_total",
            "Load balancing strategy selections per model",
            ["strategy", "model_name"],
            registry=self._registry,
        )

        # ------------------------------------------------------------------
        # B. Pipeline / Request Funnel
        # ------------------------------------------------------------------
        self.PIPELINE_STAGE = Counter(
            "llm_router_pipeline_stage_total",
            "Request counts at each pipeline stage",
            ["stage", "result"],
            registry=self._registry,
        )

        self.RETRY = Counter(
            "llm_router_retry_total",
            "Total retry attempts per model and error code",
            ["model_name", "error_code"],
            registry=self._registry,
        )

        self.RETRY_EXHAUSTED = Counter(
            "llm_router_retry_exhausted_total",
            "Requests where all retry attempts were exhausted",
            ["model_name", "last_error_code"],
            registry=self._registry,
        )

        # ------------------------------------------------------------------
        # C. Token Usage
        # ------------------------------------------------------------------
        self.TOKENS = Counter(
            "llm_router_tokens_total",
            "Token usage (input / output) per model and provider",
            ["model_name", "direction", "provider_type"],
            registry=self._registry,
        )

        # ------------------------------------------------------------------
        # D. Streaming & Response Format
        # ------------------------------------------------------------------
        self.RESPONSE_FORMAT = Counter(
            "llm_router_response_format_total",
            "Response format (streamed / non_streamed) by provider and model",
            ["format", "model_name", "provider_type"],
            registry=self._registry,
        )

        self.PAYLOAD_CONVERSION = Counter(
            "llm_router_payload_conversion_total",
            "Number of payload conversions between provider types",
            ["from_type", "to_type"],
            registry=self._registry,
        )

    # ------------------------------------------------------------------
    # A. Routing & Provider helpers
    # ------------------------------------------------------------------

    def record_provider_call(self, provider_type: str, model_name: str) -> None:
        """Record a successful call to an external provider."""
        if self._registry is None:
            return
        self.PROVIDER_CALLS.labels(
            provider_type=provider_type, model_name=model_name
        ).inc()

    def record_provider_latency(self, provider_type: str, model_name: str, seconds: float) -> None:
        """Record the latency of an outbound provider call."""
        if self._registry is None:
            return
        self.PROVIDER_LATENCY.labels(
            provider_type=provider_type, model_name=model_name
        ).observe(seconds)

    def record_provider_error(self, provider_type: str, model_name: str, error_code: str) -> None:
        """Record a provider error."""
        if self._registry is None:
            return
        self.PROVIDER_ERROR.labels(
            provider_type=provider_type, model_name=model_name, error_code=error_code
        ).inc()

    def record_lb_strategy(self, strategy: str, model_name: str) -> None:
        """Record a load-balancing strategy selection."""
        if self._registry is None:
            return
        self.LB_STRATEGY_SELECTED.labels(
            strategy=strategy, model_name=model_name
        ).inc()

    # ------------------------------------------------------------------
    # B. Pipeline helpers
    # ------------------------------------------------------------------

    def record_pipeline_stage(self, stage: str, result: str) -> None:
        """Record a pipeline stage completion."""
        if self._registry is None:
            return
        self.PIPELINE_STAGE.labels(stage=stage, result=result).inc()

    def record_retry(self, model_name: str, error_code: str) -> None:
        """Record a retry attempt."""
        if self._registry is None:
            return
        self.RETRY.labels(model_name=model_name, error_code=error_code).inc()

    def record_retry_exhausted(self, model_name: str, last_error_code: str) -> None:
        """Record that all retries were exhausted (final failure)."""
        if self._registry is None:
            return
        self.RETRY_EXHAUSTED.labels(
            model_name=model_name, last_error_code=last_error_code
        ).inc()

    # ------------------------------------------------------------------
    # C. Token usage helpers
    # ------------------------------------------------------------------

    def record_tokens(self, model_name: str, direction: str, count: int, provider_type: str = "unknown") -> None:
        """Record token usage (input or output)."""
        if self._registry is None:
            return
        self.TOKENS.labels(
            model_name=model_name, direction=direction, provider_type=provider_type
        ).inc(count)

    # ------------------------------------------------------------------
    # D. Streaming & format helpers
    # ------------------------------------------------------------------

    def record_response_format(self, fmt: str, model_name: str, provider_type: str) -> None:
        """Record response format (streamed / non_streamed)."""
        if self._registry is None:
            return
        self.RESPONSE_FORMAT.labels(
            format=fmt, model_name=model_name, provider_type=provider_type
        ).inc()

    def record_payload_conversion(self, from_type: str, to_type: str) -> None:
        """Record a payload type conversion (e.g. openai->ollama)."""
        if self._registry is None:
            return
        self.PAYLOAD_CONVERSION.labels(
            from_type=from_type, to_type=to_type
        ).inc()
