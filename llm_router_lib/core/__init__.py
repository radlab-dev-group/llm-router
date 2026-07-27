"""
Central configuration values for ``llm_router_lib``.

All magic numbers that appear in both *http.py* and *client.py* (timeouts,
retries) as well as default generation parameters live here so they can be
changed in a single place without risk of accidental drift.
"""

from llm_router_lib.core.constants import (
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_RETRIES,
    RETRY_BACKOFF_FACTOR,
    RETRY_STATUS_CODELIST,
    DEFAULT_TEMPERATURE,
    DEFAULT_MAX_NEW_TOKENS,
    DEFAULT_TOP_K,
    DEFAULT_TOP_P,
    DEFAULT_TYPICAL_P,
    DEFAULT_REPETITION_PENALTY,
    DEFAULT_KEEP_ALIVE,
    DEFAULT_OPTIONS,
)

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_RETRIES",
    "RETRY_BACKOFF_FACTOR",
    "RETRY_STATUS_CODELIST",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_MAX_NEW_TOKENS",
    "DEFAULT_TOP_K",
    "DEFAULT_TOP_P",
    "DEFAULT_TYPICAL_P",
    "DEFAULT_REPETITION_PENALTY",
    "DEFAULT_KEEP_ALIVE",
    "DEFAULT_OPTIONS",
]
