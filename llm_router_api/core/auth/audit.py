"""
Authentication auditor — bridges auth events to the existing
AnyRequestAuditor for compliance/logging.
"""

from __future__ import annotations

from typing import Any

from llm_router_api.core.auditor.auditor import AnyRequestAuditor


class AuthAuditorBridge:
    """
    Bridge between auth middleware and AnyRequestAuditor.

    When ``LLM_ROUTER_AUTH_AUDIT`` is enabled, every auth event
    (success, failure, rate limit) is forwarded to the auditor for
    persistence (GPG-encrypted, Kafka, etc.).
    """

    def __init__(self, auditor: AnyRequestAuditor | None = None) -> None:
        self._auditor = auditor

    def record_event(
        self,
        event_type: str,
        reason: str,
        key_id: str | None = None,
        endpoint: str | None = None,
        model: str | None = None,
        extra: dict | None = None,
    ) -> None:
        """
        Record an auth event.

        Parameters
        ----------
        event_type : str
            One of ``"auth_success"``, ``"auth_failure"``, ``"rate_limit"``.
        reason : str
            Auth result reason code.
        key_id : str | None
            The authenticated key ID (if any).
        endpoint : str | None
            The endpoint path.
        model : str | None
            The model being accessed.
        extra : dict | None
            Additional context (IP, user-agent, …).
        """
        if self._auditor is None:
            return

        audit_log = {
            "audit_type": "auth_event",
            "event_type": event_type,
            "reason": reason,
            "key_id": key_id,
            "endpoint": endpoint,
            "model": model,
            "timestamp": __import__("time").time(),
        }
        if extra:
            audit_log["extra"] = extra

        self._auditor.add_log(audit_log)
