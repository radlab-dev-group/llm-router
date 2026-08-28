"""
Authentication auditor — bridges auth events to the existing
AnyRequestAuditor for compliance/logging.
"""

from __future__ import annotations

from typing import Dict, Optional

from llm_router_api.core.auditor.auditor import AnyRequestAuditor


class AuthAuditorBridge:
    """
    Bridge between auth middleware and AnyRequestAuditor.

    When ``LLM_ROUTER_AUTH_AUDIT`` is enabled, every auth event
    (success, failure, rate limit) is forwarded to the auditor for
    persistence (GPG-encrypted, Kafka, etc.).
    """

    def __init__(self, auditor: Optional[AnyRequestAuditor] = None) -> None:
        self._auditor = auditor

    def record_event(
        self,
        event_type: str,
        reason: str,
        key_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        model: Optional[str] = None,
        extra: Optional[Dict] = None,
    ) -> None:
        """
        Record an auth event.

        Parameters
        ----------
        event_type : str
            One of ``"auth_success"``, ``"auth_failure"``, ``"rate_limit"``.
        reason : str
            Auth result reason code.
        key_id : Optional[str]
            The authenticated key ID (if any).
        endpoint : Optional[str]
            The endpoint path.
        model : Optional[str]
            The model being accessed.
        extra : Optional[Dict]
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
