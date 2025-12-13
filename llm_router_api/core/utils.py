"""Utility helpers for load‑balancing strategies.

The :class:`StrategyHelpers` class groups small, pure‑function helpers that
are used across the routing strategies.  All helpers operate on data that
originates from Redis or provider configuration dictionaries and therefore
need to be tolerant of ``None`` values and binary payloads.

The original Polish comments have been replaced with English docstrings,
and each public method now has a clear description of its behavior,
parameters, and return value.
"""

from typing import Optional, Any


class StrategyHelpers:
    """
    Static utility methods for dealing with Redis values and provider data.
    """

    @staticmethod
    def decode_redis(value: Any) -> Optional[str]:
        """
        Convert a Redis return value to a UTF‑8 string.

        Redis commands may return ``bytes``, ``bytearray`` or ``None``.
        This helper normalizes those possibilities to a plain Python ``str``,
        returning ``None`` when the input is ``None``.

        Parameters
        ----------
        value: Any
            The raw value returned by a Redis call.

        Returns
        -------
        str | None
            Decoded UTF‑8 string, or ``None`` if ``value`` was ``None``.
        """
        if value is None:
            return None
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8", errors="ignore")
        return str(value)

    @staticmethod
    def normalize_model_name(name: Optional[str]) -> str:
        """
        Produce a canonical representation of a model name.

        The function removes common prefixes (``model:``, ``host:``), trims
        surrounding whitespace, and guarantees that a string is always
        returned (empty string for falsy input).

        Parameters
        ----------
        name: str | None
            Raw model name possibly containing prefixes.

        Returns
        -------
        str
            Normalised model name without prefixes and without surrounding
            whitespace.
        """
        if not name:
            return ""
        s = str(name).strip()
        if s.startswith("model:"):
            s = s[len("model:") :]
        if s.startswith("host:"):
            s = s[len("host:") :]
        return s.strip()

    @staticmethod
    def host_from_provider(provider) -> Optional[str]:
        """
        Extract the host identifier from a provider configuration.

        Provider dictionaries may store the host under either ``api_host`` or
        ``host`` keys; this helper checks both and returns the first non‑empty
        value.

        Parameters
        ----------
        provider: dict
            Provider configuration dictionary.

        Returns
        -------
        str | None
            Host URL if present, otherwise ``None``.
        """
        return provider.get("api_host") or provider.get("host")
