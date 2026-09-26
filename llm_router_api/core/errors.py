"""
Utility helpers for representing API errors as JSON‑serializable dictionaries.

This module centralizes the creation of error payloads that can be returned from
Flask (or any other) endpoints.  By keeping the structure in one place, we avoid
repetition and make it easy to evolve the error format in the future.
"""

import re

from typing import Dict, Any, Optional


# Error code used when a request is missing one or more mandatory parameters.
ERROR_NO_REQUIRED_PARAMS = "No required parameters!"


def error_as_dict(error: str, error_msg: Optional[str] = None) -> Dict[str, Any]:
    """
    Convert an error identifier and optional message into a serialisable dictionary.

    Parameters
    ----------
    error : str
        A short, machine‑readable error code or identifier.
    error_msg : Optional[str], default ``None``
        A human‑readable description providing additional context.
        If omitted, only the ``error`` key is included in the result.

    Returns
    -------
    Dict[str, Any]
        A dictionary suitable for JSON responses, containing at least the
        ``"error"`` key and, when ``error_msg`` is supplied, a ``"message"``
        key.

    Examples
    --------
    >>> error_as_dict("INVALID_INPUT")
    {'error': 'INVALID_INPUT'}

    >>> error_as_dict("INVALID_INPUT", "The provided ID is not a UUID")
    {'error': 'INVALID_INPUT', 'message': 'The provided ID is not a UUID'}
    """
    if error_msg is None:
        return {"error": error}

    return {"error": error, "message": error_msg}


def sanitize_error_message(message: str) -> str:
    """
    Strip network-sensitive details (URLs, IPs, ports, hostnames) from an error
    message, so it is safe to return to an API caller.

    Server-side logging keeps the original (full) message — only messages sent
    to the client are sanitized.

    The function is **idempotent** (calling it twice produces the same result)
    and fast (pure regex, no I/O).

    Examples
    --------
    >>> sanitized = sanitize_error_message(
    ...     "HTTPConnectionPool(host='10.0.1.50', port=8080): "
    ...     "Max retries exceeded with url: /v1/chat (Caused by "
    ...     "ConnectTimeoutError: 'Connection to 10.0.1.50 timed out. "
    ...     "'(connect timeout=1)'))"
    ... )
    >>> '10.0.1.50' not in sanitized
    True
    >>> '8080' not in sanitized
    True
    """
    msg = message

    # Strip all URLs
    msg = re.sub(r"https?://\S+", "", msg)

    # Strip host/port parameters from urllib3 error messages
    msg = re.sub(r"host=['\"][^'\"]+['\"]", "", msg)
    msg = re.sub(r"port=\d+", "", msg)

    # Strip [IP:PORT] bracket patterns
    msg = re.sub(r"\[\d+\.\d+\.\d+\.\d+:\d+\]", "", msg)

    # Strip "Connection to X.X.X.X ..." / "Connection refused by X.X.X.X ..."
    msg = re.sub(
        r"Connection (to|refused by)"
        r"\s*['\"]?\d+\.\d+\.\d+\.\d+['\"]?(?:\s*\[[^\]]*\])?\s*(?:'[^']*')?",
        "",
        msg,
    )

    # Strip <urllib3...> object references
    msg = re.sub(r"<urllib3\.\w+\s+object\s+at\s+0x[0-9a-fA-F]+>", "", msg)

    # Strip wrapper exception context
    msg = re.sub(r"HTTPConnectionPool\([^)]*\)\s*:\s*", "", msg)
    msg = re.sub(r"Max retries exceeded with url:\s*", "", msg)
    msg = re.sub(r"\(Caused by\s*\w+Error:\s*", "(", msg)
    msg = re.sub(r"ConnectTimeoutError:\s*", "", msg)
    msg = re.sub(r"NewConnectionError:\s*", "", msg)

    # Collapse whitespace and strip punctuation left by removals
    msg = re.sub(r"\s+", " ", msg).strip()
    msg = re.sub(r"^[.:;\s]+|[.:;\s]+$", "", msg)

    # Strip trailing/leading parenthetical noise left behind
    msg = re.sub(r"\(\s*'\s*\.?\s*'\s*\)\s*\)*", "", msg)
    msg = re.sub(r"^[.:;\s]+|[.:;\s]+$", "", msg)

    if not msg:
        return "A connection error occurred"

    return msg


class ProviderStreamError(Exception):
    """
    A provider rejected a **streaming** request before any content was produced.

    The streaming helpers issue the request, check the status and only then
    start yielding chunks, so a non‑2xx answer always arrives while nothing has
    been sent to the client yet.  In that situation retrying on another
    provider is safe, and this exception is the signal that lets the HTTP
    dispatcher do it (falling back to the model's ``fallback_model`` only once
    every provider of the model failed too).

    It deliberately does **not** derive from ``requests.RequestException`` —
    the per‑format generators catch that type to emit their final error chunk,
    which would swallow the failover signal.

    Attributes
    ----------
    status_code : int
        HTTP status returned by the provider.
    message : str
        Client-safe description (same text the stream would have emitted).
    provider_body : str
        Raw provider response fragment, for server-side logging only.
    """

    def __init__(
        self, status_code: int, message: str, provider_body: str = ""
    ) -> None:
        super().__init__(message)
        self.status_code = int(status_code)
        self.message = message
        self.provider_body = provider_body or ""
