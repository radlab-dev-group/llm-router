"""
Central configuration values for ``llm_router_lib``.

All magic numbers that appear in both *http.py* and *client.py* (timeouts,
retries) as well as default generation parameters live here so they can be
changed in a single place without risk of accidental drift.
"""

import os

from typing import Dict, List

# ------------------------------------------------------------------ #
# Shared environment prefix + default endpoint language
# ------------------------------------------------------------------ #

# Common prefix for all LLM_ROUTER_* environment variables.  Kept in the
# dependency‑free library layer so the API package can re‑export it for
# backward compatibility.
ENV_PREFIX = "LLM_ROUTER_"

# Default language for endpoint‑specific prompts.  The value can be overridden
# with the environment variable LLM_ROUTER_DEFAULT_EP_LANGUAGE.
# If the variable is absent, Polish ("pl") is used as the fallback language.
DEFAULT_EP_LANGUAGE = os.environ.get(
    f"{ENV_PREFIX}DEFAULT_EP_LANGUAGE", "pl"
).strip()

# ------------------------------------------------------------------ #
# HTTP client defaults
# ------------------------------------------------------------------ #

DEFAULT_TIMEOUT_SECONDS: int = 10
DEFAULT_RETRIES: int = 2
RETRY_BACKOFF_FACTOR: float = 0.5
RETRY_STATUS_CODELIST: List[int] = [429, 500, 502, 503, 504]

# ------------------------------------------------------------------ #
# Default generation parameters (used by builtin_chat.py / openai.py)
# ------------------------------------------------------------------ #

DEFAULT_TEMPERATURE: float = 0.75
DEFAULT_MAX_NEW_TOKENS: int = 256
DEFAULT_TOP_K: int = 50
DEFAULT_TOP_P: float = 0.99
DEFAULT_TYPICAL_P: float = 1.0
DEFAULT_REPETITION_PENALTY: float = 1.2

# OpenAI‑compatible endpoint defaults
DEFAULT_KEEP_ALIVE: str = "30m"
DEFAULT_OPTIONS: Dict[str, int] = {"num_ctx": 128_000}
