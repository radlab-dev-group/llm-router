"""
Unit tests for ``llm_router_api.core.auth.audit.AuthAuditorBridge``.

The bridge forwards auth events to an ``AnyRequestAuditor``; the auditor
is stubbed with a mock so no storage backend is touched.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import time  # noqa: E402
from unittest import mock  # noqa: E402

from llm_router_api.core.auth.audit import AuthAuditorBridge  # noqa: E402


class TestRecordEventNoAuditor:
    def test_no_op_without_auditor(self):
        bridge = AuthAuditorBridge()
        # Must not raise even with no auditor configured.
        bridge.record_event(
            event_type="auth_failure",
            reason="invalid_key",
            key_id="key-1",
        )

    def test_no_op_when_auditor_is_none(self):
        bridge = AuthAuditorBridge(auditor=None)
        bridge.record_event(
            event_type="auth_success", reason="ok", extra={"ip": "1.2.3.4"}
        )


class TestRecordEventWithAuditor:
    def test_payload_fields(self):
        auditor = mock.Mock()
        bridge = AuthAuditorBridge(auditor=auditor)
        before = time.time()

        bridge.record_event(
            event_type="auth_failure",
            reason="invalid_key",
            key_id="key-1",
            endpoint="/v1/chat",
            model="gpt-x",
        )

        auditor.add_log.assert_called_once()
        payload = auditor.add_log.call_args[0][0]
        assert payload["audit_type"] == "auth_event"
        assert payload["event_type"] == "auth_failure"
        assert payload["reason"] == "invalid_key"
        assert payload["key_id"] == "key-1"
        assert payload["endpoint"] == "/v1/chat"
        assert payload["model"] == "gpt-x"
        assert before <= payload["timestamp"] <= time.time()
        assert "extra" not in payload

    def test_extra_included_when_provided(self):
        auditor = mock.Mock()
        bridge = AuthAuditorBridge(auditor=auditor)

        bridge.record_event(
            event_type="rate_limit",
            reason="rate_limit",
            extra={"ip": "10.0.0.1", "user_agent": "ua"},
        )

        payload = auditor.add_log.call_args[0][0]
        assert payload["extra"] == {"ip": "10.0.0.1", "user_agent": "ua"}

    def test_defaults_when_optional_fields_missing(self):
        auditor = mock.Mock()
        bridge = AuthAuditorBridge(auditor=auditor)

        bridge.record_event(event_type="auth_success", reason="ok")

        payload = auditor.add_log.call_args[0][0]
        assert payload["key_id"] is None
        assert payload["endpoint"] is None
        assert payload["model"] is None
