"""
Auth error codes and messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AuthResult:
    """
    Result of the authentication & authorization check.

    Attributes
    ----------
    allowed : bool
        Whether the request should be allowed to proceed.
    reason : str
        Code describing the result (used for logging and error messages).
    status_code : int
        HTTP status code to return (401, 403, 429, …).
    headers : dict[str, str]
        Additional headers to include in the response.
    key_id : str
        The authenticated key ID (only when ``allowed=True``).
    """

    allowed: bool
    reason: str
    status_code: int
    headers: dict[str, str] = None  # type: ignore[assignment]
    key_id: str | None = None

    def __post_init__(self) -> None:
        if self.headers is None:
            object.__setattr__(self, "headers", {})


# -- reason → message mapping ----------------------------
_AUTH_MESSAGES: dict[str, str] = {
    "missing_key": "API key not provided. Send it in the Authorization header or as x-api-key.",
    "invalid_key": "API key not found or invalid.",
    "key_inactive": "This API key has been deactivated.",
    "key_expired": "This API key has expired.",
    "key_rotated": "This API key has been rotated. Use the new key.",
    "key_grace_expired": "This API key is no longer valid.",
    "policy_inactive": "The policy for this API key is inactive.",
    "endpoint_not_in_policy": "This API key does not have access to this endpoint.",
    "endpoint_denied_by_policy": "Access to this endpoint is denied by policy.",
    "method_not_allowed": "This HTTP method is not allowed for this endpoint.",
    "ip_not_whitelisted": "Your IP address is not allowed.",
    "model_not_in_whitelist": "This model is not allowed for this key.",
    "budget_exceeded": "Monthly token budget has been exceeded.",
    "rate_limit": "Rate limit exceeded. Please retry later.",
    "unknown_endpoint": "Unknown endpoint.",
}


def auth_error_message(reason: str) -> str:
    """Return a human-readable message for an auth failure reason."""
    return _AUTH_MESSAGES.get(reason, f"Authentication failed: {reason}")


def auth_error_response(reason: str, status_code: int) -> dict[str, Any]:
    """
    Build an OpenAI-compatible error response for authentication failures.

    Returns
    -------
    dict
        JSON-serializable error response.
    """
    message = auth_error_message(reason)
    return {
        "error": {
            "message": message,
            "type": "authentication_error",
            "param": None,
            "code": status_code,
        }
    }


def auth_429_response(retry_after: int) -> dict[str, Any]:
    """Build a 429 Too Many Requests response."""
    return {
        "error": {
            "message": "Rate limit exceeded.",
            "type": "rate_limit_error",
            "param": None,
            "code": 429,
        }
    }, retry_after
