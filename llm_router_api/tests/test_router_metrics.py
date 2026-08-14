"""
Tests for ``llm_router_api.core.router_metrics``.

Verifies:
- Metric registration and recording helpers exist with correct attributes
- No-op behavior when Prometheus is not available
- All 10 metric types are present and recording works correctly
"""

from __future__ import annotations

import os as _os

# Set required env vars BEFORE any llm_router imports to avoid startup validation.
for _k in ("LLM_ROUTER_MINIMUM", "LLM_ROUTER_USE_PROMETHEUS"):
    _os.environ.setdefault(_k, "1")

from unittest import mock

import pytest


class TestRouterMetricsNoOp:
    """When Prometheus is unavailable, all methods should be no-ops."""

    @pytest.fixture(autouse=True)
    def _mock_prometheus_unavailable(self):
        with mock.patch(
            "llm_router_api.core.router_metrics.IS_PROMETHEUS_AVAILABLE", False
        ):
            yield

    def test_init_noop_creates_none_registry(self):
        from llm_router_api.core.router_metrics import RouterMetrics

        rm = RouterMetrics()
        assert rm._registry is None

    def test_record_all_methods_noop(self):
        from llm_router_api.core.router_metrics import RouterMetrics

        rm = RouterMetrics()

        # All recording methods should not raise
        rm.record_provider_call("openai", "gpt-4")
        rm.record_provider_latency("openai", "gpt-4", 0.5)
        rm.record_provider_error("openai", "gpt-4", "503")
        rm.record_lb_strategy("balanced", "gpt-4")
        rm.record_pipeline_stage("provider_resolved", "success")
        rm.record_retry("gpt-4", "429")
        rm.record_retry_exhausted("gpt-4", "503")
        rm.record_tokens("gpt-4", "input", 100, "openai")
        rm.record_response_format("streamed", "gpt-4", "openai")
        rm.record_payload_conversion("openai", "ollama")


class TestRouterMetricsAttributes:
    """Verify all metric attributes exist on RouterMetrics with valid prometheus types."""

    @pytest.fixture(autouse=True)
    def _mock_full_prometheus(self, monkeypatch):
        """Mock the entire prometheus_client module to avoid real registration."""
        fake_counter = mock.MagicMock()
        fake_histogram = mock.MagicMock()
        fake_registry_cls = mock.MagicMock()

        # Create mock metric objects that behave like prometheus metrics
        mock_counter_obj = mock.MagicMock()
        mock_hist_obj = mock.MagicMock()

        fake_counter.return_value = mock_counter_obj
        fake_histogram.return_value = mock_hist_obj

        monkeypatch.setattr(
            "llm_router_api.core.router_metrics.IS_PROMETHEUS_AVAILABLE", True
        )
        monkeypatch.setattr(
            "llm_router_api.core.router_metrics.Counter", fake_counter
        )
        monkeypatch.setattr(
            "llm_router_api.core.router_metrics.Histogram", fake_histogram
        )
        monkeypatch.setattr(
            "llm_router_api.core.router_metrics.CollectorRegistry", fake_registry_cls
        )
        yield

    def test_all_metrics_registered(self):
        from llm_router_api.core.router_metrics import RouterMetrics

        rm = RouterMetrics()

        # Verify all metric attributes exist and are not None
        assert rm.PROVIDER_CALLS is not None
        assert rm.PROVIDER_LATENCY is not None
        assert rm.PROVIDER_ERROR is not None
        assert rm.LB_STRATEGY_SELECTED is not None
        assert rm.PIPELINE_STAGE is not None
        assert rm.RETRY is not None
        assert rm.RETRY_EXHAUSTED is not None
        assert rm.TOKENS is not None
        assert rm.RESPONSE_FORMAT is not None
        assert rm.PAYLOAD_CONVERSION is not None

    def test_custom_registry(self):
        from llm_router_api.core.router_metrics import RouterMetrics

        custom_registry = object()  # dummy registry
        rm = RouterMetrics(registry=custom_registry)
        assert rm._registry is custom_registry


class TestRouterMetricsRecordingHelpers:
    """Verify recording helpers call the correct metric with correct labels."""

    @pytest.fixture(autouse=True)
    def _mock_full_prometheus(self, monkeypatch):
        fake_counter = mock.MagicMock()
        fake_histogram = mock.MagicMock()
        fake_registry_cls = mock.MagicMock()

        mock_counter_obj = mock.MagicMock()
        mock_hist_obj = mock.MagicMock()

        fake_counter.return_value = mock_counter_obj
        fake_histogram.return_value = mock_hist_obj

        monkeypatch.setattr(
            "llm_router_api.core.router_metrics.IS_PROMETHEUS_AVAILABLE", True
        )
        monkeypatch.setattr(
            "llm_router_api.core.router_metrics.Counter", fake_counter
        )
        monkeypatch.setattr(
            "llm_router_api.core.router_metrics.Histogram", fake_histogram
        )
        monkeypatch.setattr(
            "llm_router_api.core.router_metrics.CollectorRegistry", fake_registry_cls
        )
        yield

    def test_record_provider_calls(self):
        from llm_router_api.core.router_metrics import RouterMetrics

        rm = RouterMetrics()
        rm.record_provider_call("openai", "gpt-4")

        mock_counter_obj = rm.PROVIDER_CALLS
        # Verify the labels call was made with correct args
        assert mock_counter_obj.labels.called
        call_args = mock_counter_obj.labels.call_args
        assert call_args[1]["provider_type"] == "openai"
        assert call_args[1]["model_name"] == "gpt-4"

    def test_record_provider_latency(self):
        from llm_router_api.core.router_metrics import RouterMetrics

        rm = RouterMetrics()
        rm.record_provider_latency("ollama", "gemma-3-12b-it", 0.5)

        mock_hist_obj = rm.PROVIDER_LATENCY
        assert mock_hist_obj.labels.called
        call_args = mock_hist_obj.labels.call_args
        assert call_args[1]["provider_type"] == "ollama"
        assert call_args[1]["model_name"] == "gemma-3-12b-it"

    def test_record_provider_error(self):
        from llm_router_api.core.router_metrics import RouterMetrics

        rm = RouterMetrics()
        rm.record_provider_error("vllm", "gemma-3-12b-it", "503")

        mock_counter_obj = rm.PROVIDER_ERROR
        assert mock_counter_obj.labels.called
        call_args = mock_counter_obj.labels.call_args
        assert call_args[1]["provider_type"] == "vllm"
        assert call_args[1]["model_name"] == "gemma-3-12b-it"
        assert call_args[1]["error_code"] == "503"

    def test_record_lb_strategy(self):
        from llm_router_api.core.router_metrics import RouterMetrics

        rm = RouterMetrics()
        rm.record_lb_strategy("weighted", "google/gemma-3-12b-it")

        mock_counter_obj = rm.LB_STRATEGY_SELECTED
        assert mock_counter_obj.labels.called
        call_args = mock_counter_obj.labels.call_args
        assert call_args[1]["strategy"] == "weighted"
        assert call_args[1]["model_name"] == "google/gemma-3-12b-it"

    def test_record_pipeline_stage(self):
        from llm_router_api.core.router_metrics import RouterMetrics

        rm = RouterMetrics()
        rm.record_pipeline_stage("provider_resolved", "success")

        mock_counter_obj = rm.PIPELINE_STAGE
        assert mock_counter_obj.labels.called
        call_args = mock_counter_obj.labels.call_args
        assert call_args[1]["stage"] == "provider_resolved"
        assert call_args[1]["result"] == "success"

    def test_record_retry(self):
        from llm_router_api.core.router_metrics import RouterMetrics

        rm = RouterMetrics()
        rm.record_retry("gpt-oss:120b", "429")

        mock_counter_obj = rm.RETRY
        assert mock_counter_obj.labels.called
        call_args = mock_counter_obj.labels.call_args
        assert call_args[1]["model_name"] == "gpt-oss:120b"
        assert call_args[1]["error_code"] == "429"

    def test_record_retry_exhausted(self):
        from llm_router_api.core.router_metrics import RouterMetrics

        rm = RouterMetrics()
        rm.record_retry_exhausted("gpt-oss:120b", "503")

        mock_counter_obj = rm.RETRY_EXHAUSTED
        assert mock_counter_obj.labels.called
        call_args = mock_counter_obj.labels.call_args
        assert call_args[1]["model_name"] == "gpt-oss:120b"
        assert call_args[1]["last_error_code"] == "503"

    def test_record_tokens(self):
        from llm_router_api.core.router_metrics import RouterMetrics

        rm = RouterMetrics()
        rm.record_tokens("google/gemma-3-12b-it", "input", 100, "vllm")

        mock_counter_obj = rm.TOKENS
        assert mock_counter_obj.labels.called
        call_args = mock_counter_obj.labels.call_args
        assert call_args[1]["model_name"] == "google/gemma-3-12b-it"
        assert call_args[1]["direction"] == "input"
        assert call_args[1]["provider_type"] == "vllm"

    def test_record_response_format(self):
        from llm_router_api.core.router_metrics import RouterMetrics

        rm = RouterMetrics()
        rm.record_response_format("streamed", "gpt-4", "openai")

        mock_counter_obj = rm.RESPONSE_FORMAT
        assert mock_counter_obj.labels.called
        call_args = mock_counter_obj.labels.call_args
        assert call_args[1]["format"] == "streamed"
        assert call_args[1]["model_name"] == "gpt-4"
        assert call_args[1]["provider_type"] == "openai"

    def test_record_payload_conversion(self):
        from llm_router_api.core.router_metrics import RouterMetrics

        rm = RouterMetrics()
        rm.record_payload_conversion("openai", "ollama")

        mock_counter_obj = rm.PAYLOAD_CONVERSION
        assert mock_counter_obj.labels.called
        call_args = mock_counter_obj.labels.call_args
        assert call_args[1]["from_type"] == "openai"
        assert call_args[1]["to_type"] == "ollama"
