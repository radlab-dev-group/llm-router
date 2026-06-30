"""
Abstract base class for API key stores.

Every concrete store (Vault, Redis, Memory) implements this interface so that
the auth middleware can treat them interchangeably.
"""

from __future__ import annotations

import abc
import asyncio

from typing import Any


class KeyStoreInterface(metaclass=abc.ABCMeta):
    """
    Interface that all key stores must implement.

    The store is the single source of truth for API keys — it holds the
    authoritative record for every issued key together with its policy.
    """

    @staticmethod
    def _run_async(coro) -> Any:
        """Run an async coroutine from a synchronous context.

        If a running event loop exists, schedules *coro* on it via
        ``asyncio.run_coroutine_threadsafe``.  Otherwise runs it with
        ``asyncio.run()``.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        import asyncio as _asyncio  # pylint: disable=reimport

        return _asyncio.run_coroutine_threadsafe(
            coro, _asyncio.get_running_loop()
        ).result()

    @abc.abstractmethod
    async def get_key_by_hash(self, key_hash: str) -> Any | None:
        """
        Look up a key record by its **bcrypt** hash.

        Parameters
        ----------
        key_hash : str
            The bcrypt hash of the plaintext API key (``$2b$…``).

        Returns
        -------
        ApiKeyRecord | None
            The matching record, or ``None`` when the key does not exist.
        """

    @abc.abstractmethod
    def get_key_by_hash_sync(self, key_hash: str) -> Any | None:
        """
        Synchronous version of :meth:`get_key_by_hash`.

        Call this from synchronous contexts (e.g. Flask ``before_request``).
        Internally dispatches to the async method via the running event loop.
        """

    @abc.abstractmethod
    async def get_key_by_id(self, key_id: str) -> Any | None:
        """
        Look up a key record by its ``key_id``.

        Parameters
        ----------
        key_id : str
            The unique identifier of the key (e.g. ``"key-001"``).

        Returns
        -------
        ApiKeyRecord | None
            The matching record, or ``None`` when the key does not exist.
        """

    @abc.abstractmethod
    async def create_key(self, record: dict) -> str:
        """
        Store a new API key.

        Parameters
        ----------
        record : dict
            Dictionary containing at least ``"key_plain"`` (the raw secret).
            The rest of the record describes policy, expiry, etc.

        Returns
        -------
        str
            The **plaintext** key — returned *only once*, at creation time.

        Notes
        -----
        The concrete store MUST hash the plaintext key (bcrypt) before
        persisting.  The plaintext must *never* be stored.
        """

    @abc.abstractmethod
    async def rotate_key(self, key_id: str, grace_period: int) -> str:
        """
        Rotate (renew) an existing key.

        Parameters
        ----------
        key_id : str
            The key to rotate.
        grace_period : int
            Number of seconds the *old* key remains valid (``grace_until``).

        Returns
        -------
        str
            The new plaintext key (returned once to the caller).
        """

    @abc.abstractmethod
    async def disable_key(self, key_id: str) -> None:
        """
        Deactivate (but do not delete) a key by setting ``is_active=False``.

        Parameters
        ----------
        key_id : str
            The key to deactivate.
        """

    @abc.abstractmethod
    async def enable_key(self, key_id: str) -> None:
        """
        Re-activate a previously deactivated key by setting ``is_active=True``.

        Parameters
        ----------
        key_id : str
            The key to activate.
        """

    @abc.abstractmethod
    async def delete_key(self, key_id: str) -> None:
        """
        Deactivate and remove a key.

        Parameters
        ----------
        key_id : str
            The key to delete.
        """

    @abc.abstractmethod
    async def list_keys(self) -> list[Any]:
        """
        List all key records (for CLI ``auth key list``).

        Returns
        -------
        list[ApiKeyRecord]
        """
