"""
Prometheus metrics for the auth layer.

These metrics are registered alongside the existing HTTP metrics when
Prometheus is enabled (``LLM_ROUTER_USE_PROMETHEUS=true``).
"""

from __future__ import annotations

import os

from llm_router_api.core.metrics_handler import MetricsHandler


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
        Gauge,
        Histogram,
    )

    _REGISTRY = CollectorRegistry()
    multiprocess.MultiProcessCollector(_REGISTRY)

    IS_PROMETHEUS_AVAILABLE = True
except ImportError:
    IS_PROMETHEUS_AVAILABLE = False


class AuthMetrics:
    """Prometheus metrics for authentication."""

    def __init__(self, registry=None) -> None:
        if not IS_PROMETHEUS_AVAILABLE:
            self._registry = None
            return

        self._registry = registry or _REGISTRY

        # Total auth attempts by result
        self.TOTAL = Counter(
            "auth_attempts_total",
            "Total authentication attempts by result",
            ["result", "key_id"],
            registry=self._registry,
        )

        # Auth latency breakdown
        self.LATENCY = Histogram(
            "auth_latency_seconds",
            "Latency of authentication (seconds)",
            ["step"],
            registry=self._registry,
        )

        # Rate limit events
        self.RATE_LIMIT = Counter(
            "rate_limit_exceeded_total",
            "Total rate limit exceeded events",
            ["key_id", "endpoint"],
            registry=self._registry,
        )

        # Key budget usage
        self.BUDGET = Gauge(
            "key_budget_usage_tokens",
            "Current token budget usage for a key",
            ["key_id", "budget_total"],
            registry=self._registry,
        )

    def record_attempt(self, result: str, key_id: str = "unknown") -> None:
        """Record an authentication attempt result."""
        if self._registry is None:
            return
        self.TOTAL.labels(result=result, key_id=key_id).inc()

    def record_latency(self, step: str, seconds: float) -> None:
        """Record the latency of an auth step
        (extract, authenticate, authorize, etc.)."""
        if self._registry is None:
            return
        self.LATENCY.labels(step=step).observe(seconds)

    def record_rate_limit(self, key_id: str, endpoint: str) -> None:
        """Record a rate limit event."""
        if self._registry is None:
            return
        self.RATE_LIMIT.labels(key_id=key_id, endpoint=endpoint).inc()

    def set_budget(self, key_id: str, used: int, total: int) -> None:
        """Set the current budget usage gauge for a key."""
        if self._registry is None:
            return
        self.BUDGET.labels(key_id=key_id, budget_total=total).set(used)
