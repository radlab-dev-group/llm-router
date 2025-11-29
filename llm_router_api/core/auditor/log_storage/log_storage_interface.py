"""
Abstract definition for audit‑log storage back‑ends.

Any concrete implementation must inherit from
:class:`AuditorLogStorageInterface` and provide a :meth:`store_log`
method that persists the supplied audit record.  This contract allows
different storage strategies (e.g., encrypted files, databases,
cloud buckets) to be swapped transparently in the auditing subsystem.
"""

import abc


class AuditorLogStorageInterface(abc.ABC):
    """
    Base class for audit‑log storage implementations.

    Sub‑classes are required to implement :meth:`store_log`, which
    receives a log entry and its associated ``audit_type``.  The
    interface is deliberately minimal to keep storage back‑ends
    lightweight and interchangeable.
    """

    @abc.abstractmethod
    def store_log(self, audit_log, audit_type: str):
        """
        Persist an audit log entry.

        Parameters
        ----------
        audit_log : Any
            The audit record to store.  It can be any JSON‑serialisable
            object (e.g., ``dict``, ``list``) depending on the concrete
            storage implementation.

        audit_type : str
            A string categorising the log entry (e.g., ``"request"``,
            ``"error"``).  Implementations may use this value to route
            logs to different locations or apply specific handling.

        Raises
        ------
        NotImplementedError
            If a subclass does not provide an implementation.
        """
        raise NotImplementedError
