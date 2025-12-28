"""
Utility helpers for representing API errors as JSON‑serializable dictionaries.

This module centralizes the creation of error payloads that can be returned from
Flask (or any other) endpoints.  By keeping the structure in one place, we avoid
repetition and make it easy to evolve the error format in the future.
"""

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
