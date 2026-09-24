"""
Utility helpers for load‑balancing strategies.

The :class:`StrategyHelpers` class groups small, pure‑function helpers that
are used across the routing strategies.  All helpers operate on data that
originates from Redis or provider configuration dictionaries and therefore
need to be tolerant of ``None`` values and binary payloads.

The original Polish comments have been replaced with English docstrings,
and each public method now has a clear description of its behavior,
parameters, and return value.
"""

import logging

from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


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
        Optional[str]
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
        name: Optional[str]
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
        Optional[str]
            Host URL if present, otherwise ``None``.
        """
        return provider.get("api_host") or provider.get("host")

    @staticmethod
    def nworkers(provider: Optional[Dict[str, Any]], default: int = 1) -> int:
        """
        Read the ``nworkers`` worker-slot limit from a provider config.

        The field is optional: a missing value falls back to *default*
        without any warning.  Accepted values are ``int`` and numeric
        strings (e.g. ``"4"``).  Any other or non‑positive value
        (``0``, ``-1``, ``"abc"``, ``None``, ``bool``, …) is rejected with
        a warning and *default* is returned instead, so a malformed
        configuration degrades gracefully to the safe single‑slot
        behaviour.

        Parameters
        ----------
        provider: dict or None
            Provider configuration dictionary (may be ``None``).
        default: int, optional
            Fallback limit used when the field is missing or invalid.
            Default is ``1``.

        Returns
        -------
        int
            Number of concurrent worker slots allowed on the provider
            (always ``>= 1``).
        """
        if provider is None:
            return default
        value = provider.get("nworkers")
        if value is None:
            return default

        def _fallback(reason: str) -> int:
            logger.warning(
                "Invalid 'nworkers' value %r for provider %r (%s); "
                "falling back to %d",
                value,
                provider.get("id"),
                reason,
                default,
            )
            return default

        if isinstance(value, bool) or not isinstance(value, (int, str)):
            return _fallback("expected int or numeric string")
        if isinstance(value, str):
            try:
                parsed = int(value.strip())
            except ValueError:
                return _fallback("not a numeric string")
        else:
            parsed = value
        if parsed < 1:
            return _fallback("must be >= 1")
        return parsed
