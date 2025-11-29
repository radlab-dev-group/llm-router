"""
Module providing a simple auditing mechanism for request logs.

The :class:`AnyRequestAuditor` class accepts a standard :class:`logging.Logger`
instance and forwards audit entries to a storage backend defined by
``DEFAULT_AUDITOR_STORAGE_CLASS``.  The default implementation stores logs
using GPG encryption via :class:`GPGAuditorLogStorage`.

Typical usage::

    logger = logging.getLogger(__name__)
    auditor = AnyRequestAuditor(logger)
    auditor.add_log({"audit_type": "request", "data": {...}})

"""

import logging

from llm_router_api.core.auditor.log_storage.pgp import GPGAuditorLogStorage

DEFAULT_AUDITOR_STORAGE_CLASS = GPGAuditorLogStorage


class AnyRequestAuditor:
    """Auditor for arbitrary request logs.

    Parameters
    ----------
    logger : logging.Logger
        Logger used to emit audit notifications. The logger should be
        configured by the consuming application.

    Attributes
    ----------
    logger : logging.Logger
        The logger instance provided at construction.
    _auditor_storage : GPGAuditorLogStorage
        Instance of the storage backend used to persist audit logs.
    """

    def __init__(self, logger: logging.Logger) -> None:
        """
        Create a new :class:`AnyRequestAuditor`.

        Parameters
        ----------
        logger : logging.Logger
            The logger that will receive audit warnings.
        """
        self.logger = logger
        self._auditor_storage = DEFAULT_AUDITOR_STORAGE_CLASS()

    def add_log(self, log):
        """
        Record an audit log entry.

        The ``log`` argument may be any JSON‑serialisable object – a ``dict``,
        a list of ``dict`` objects, or any other structure that can be
        serialized by the underlying storage implementation.

        The function extracts the ``audit_type`` field from the log, emits a
        warning‑level message via the configured logger, and delegates the
        actual persistence to ``_auditor_storage.store_log``.

        Parameters
        ----------
        log : dict or list
            The audit record(s) to store. Must contain an ``"audit_type"``
            key when ``log`` is a mapping.

        Raises
        ------
        KeyError
            If ``log`` is a mapping and does not contain the required
            ``"audit_type"`` key.
        """
        audit_type = log["audit_type"]
        self.logger.warning(
            f"[AUDIT] ************ Added {audit_type} audit log! ************ "
        )
        self._auditor_storage.store_log(audit_log=log, audit_type=audit_type)
