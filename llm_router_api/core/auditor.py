from typing import List


class SingleAuditLog:
    """
    Represents a single audit log entry.
    The payload should be a JSON‑serializable object (dict, list, etc.).
    """

    def __init__(self, payload):
        self.payload = payload

    def to_dict(self):
        """Return the log payload as a dictionary (if possible)."""
        if isinstance(self.payload, dict):
            return self.payload
        raise TypeError("Payload is not a dict")

    def __repr__(self):
        return f"<AuditLog payload={self.payload!r}>"


class MaskAuditor:
    def __init__(self) -> None:
        # Initialize storage for audit logs
        self._logs: List[SingleAuditLog] = []

    def add_log(self, log):
        """
        Add a log entry to the auditor.
        The log can be a dict (JSON) or any serializable object,
        including a list of such entries.
        """
        # import json
        # print("==" * 100)
        # print(json.dumps(log, indent=2, ensure_ascii=False))
        # print("==" * 100)
        self._logs.append(SingleAuditLog(log))

    def get_logs(self) -> List[SingleAuditLog]:
        """Return all collected logs."""
        return self._logs

    def audit(self) -> List[SingleAuditLog]:
        """
        Perform audit processing on collected logs.
        This placeholder can be expanded with actual audit logic.
        """
        return self._logs
