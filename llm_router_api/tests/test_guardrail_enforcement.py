"""
Tests for guardrail enforcement in ``EndpointWithHttpRequestI``.

Regression tests for the bug where guardrails were silently skipped when
the audit-log switch (``GUARDRAIL_WITH_AUDIT_REQUEST``) was disabled:
``_is_request_guardrail_safe`` short-circuited on a missing auditor, so
with ``LLM_ROUTER_FORCE_GUARDRAIL_REQUEST=1`` and audit off the guardrail
pipeline was never evaluated.  The auditor must be optional; the pipeline
must always run when configured.
"""

from __future__ import annotations

import os
from typing import Dict, Any, Tuple
from unittest import mock

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest

from llm_router_api.endpoints.builtin.builtin_chat import ConversationWithModel


class FakeGuardrailPipeline:
    """Minimal stand-in for ``GuardrailPipeline`` with a fixed verdict."""

    def __init__(self, is_safe: bool, message: str = "ok"):
        self._is_safe = is_safe
        self._message = message
        self.calls = 0

    def apply(self, payload: Dict) -> Tuple[bool, str]:
        self.calls += 1
        return self._is_safe, self._message


@pytest.fixture
def endpoint():
    return ConversationWithModel(
        logger_file_name=None,
        prompt_handler=None,
        model_handler=None,
    )


class TestRequestGuardrailEnforcement:
    """The guardrail pipeline must be evaluated regardless of audit state."""

    def test_unsafe_payload_blocked_when_audit_disabled(self, endpoint):
        pipeline = FakeGuardrailPipeline(is_safe=False, message="violated")
        endpoint._guardrails_pipeline_request = pipeline
        endpoint._guardrail_auditor_request = None  # audit off

        assert (
            endpoint._is_request_guardrail_safe(
                payload={"messages": [{"role": "user", "content": "hello"}]}
            )
            is False
        )
        assert pipeline.calls == 1

    def test_unsafe_payload_blocked_when_audit_enabled(self, endpoint):
        pipeline = FakeGuardrailPipeline(is_safe=False, message="violated")
        endpoint._guardrails_pipeline_request = pipeline
        endpoint._guardrail_auditor_request = mock.MagicMock()  # audit on

        assert (
            endpoint._is_request_guardrail_safe(
                payload={"messages": [{"role": "user", "content": "hello"}]}
            )
            is False
        )
        assert pipeline.calls == 1

    def test_safe_payload_passes_when_audit_disabled(self, endpoint):
        pipeline = FakeGuardrailPipeline(is_safe=True)
        endpoint._guardrails_pipeline_request = pipeline
        endpoint._guardrail_auditor_request = None

        assert endpoint._is_request_guardrail_safe(payload={"messages": []}) is True
        assert pipeline.calls == 1

    def test_no_pipeline_configured_passes(self, endpoint):
        endpoint._guardrails_pipeline_request = None
        endpoint._guardrail_auditor_request = None

        assert endpoint._is_request_guardrail_safe(payload={"messages": []}) is True
