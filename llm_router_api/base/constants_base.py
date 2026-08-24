"""
Base constants for the llm‑router project.
All values are read from environment variables that share the common prefix
defined in :class:_DontChangeMe. This module deliberately contains no runtime
logic – it only supplies immutable configuration values and enumerations that
are shared across the code‑base.
"""

import os


class _DontChangeMe:
    """
    Namespace for environment‑variable prefix.

    Changing the value of MAIN_ENV_PREFIX would affect every constant that reads
    from the environment, so it is isolated in its own class.
    """

    MAIN_ENV_PREFIX = "LLM_ROUTER_"


# Default language for endpoint‑specific prompts.  The value can be overridden
# with the environment variable LLM_ROUTER_DEFAULT_EP_LANGUAGE.
# If the variable is absent, Polish ("pl") is used as the fallback language.
#
# The canonical definition now lives in the dependency‑free library layer
# (``llm_router_lib.core.constants``) so that ``llm_router_lib`` does not
# import from ``llm_router_api``.  It is re‑exported here for backward
# compatibility with existing ``from llm_router_api.base.constants_base import
# DEFAULT_EP_LANGUAGE`` statements.
from llm_router_lib.core.constants import (
    DEFAULT_EP_LANGUAGE,  # noqa: F401  (re‑export for backward compatibility)
)


class BalanceStrategies:
    """
    Enumeration of supported load‑balancing strategies.

    Each attribute holds the string identifier that is expected in the
    LLM_ROUTER_BALANCE_STRATEGY environment variable. The identifiers are used
    throughout the router to decide how to pick a provider when a model
    is available from multiple back‑ends.
    """

    BALANCED = "balanced"
    WEIGHTED = "weighted"
    DYNAMIC_WEIGHTED = "dynamic_weighted"
    FIRST_AVAILABLE = "first_available"
    FIRST_AVAILABLE_OPTIM = "first_available_optim"


# List of all valid balance‑strategy identifiers.
# The router validates the user‑provided strategy against this collection
# and raises an informative error if an unknown value is supplied.
POSSIBLE_BALANCE_STRATEGIES = [
    BalanceStrategies.BALANCED,
    BalanceStrategies.WEIGHTED,
    BalanceStrategies.DYNAMIC_WEIGHTED,
    BalanceStrategies.FIRST_AVAILABLE,
    BalanceStrategies.FIRST_AVAILABLE_OPTIM,
]

#
# DEFAULT_ANONYMIZE_STRATEGY = "fast_masker"
# POSSIBLE_ANONYMIZE_STRATEGIES = ["fast_masker", "genai"]

# List of OpenAI compatible provides
OPENAI_COMPATIBLE_PROVIDERS = [
    "openai",
    "lmstudio",
    "vllm",
    "llama.cpp",
    "anthropic",
]

ALL_PROVIDERS = OPENAI_COMPATIBLE_PROVIDERS + ["ollama", "anthropic"]
