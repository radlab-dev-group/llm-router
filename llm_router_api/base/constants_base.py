"""
Base constants for the llm‑router project.
All values are read from environment variables that share the common prefix
defined in :class:_DontChangeMe. This module deliberately contains no runtime
logic – it only supplies immutable configuration values and enumerations that
are shared across the code‑base.
"""


class _DontChangeMe:
    """
    Namespace for environment‑variable prefix.

    Changing the value of MAIN_ENV_PREFIX would affect every constant that reads
    from the environment, so it is isolated in its own class.
    """

    MAIN_ENV_PREFIX = "LLM_ROUTER_"


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

# List of the OpenAI compatible providers
OPENAI_COMPATIBLE_PROVIDERS = [
    "openai",
    "lmstudio",
    "vllm",
    "llama.cpp",
    "anthropic",
]

ALL_PROVIDERS = OPENAI_COMPATIBLE_PROVIDERS + ["ollama", "anthropic"]
