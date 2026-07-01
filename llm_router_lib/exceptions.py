"""
Custom exception hierarchy for the LLM‑Router library.

All public exceptions inherit from :class:`LLMRouterError`, allowing callers
to catch a single base class for any router‑related failure while still being
able to differentiate specific error conditions when needed.
"""


class LLMRouterError(Exception):
    """Base exception for all LLM‑Router‑specific errors."""


class AuthenticationError(LLMRouterError):
    """Raised when the server returns HTTP 401/403 – invalid or missing token."""


class RateLimitError(LLMRouterError):
    """Raised when the server returns HTTP 429 – request rate limit exceeded."""


class ValidationError(LLMRouterError):
    """Raised when the server returns HTTP 400 – malformed request payload."""


class NoArgsAndNoPayloadError(LLMRouterError):
    """Raised when a client method receives neither a payload nor required arguments."""
