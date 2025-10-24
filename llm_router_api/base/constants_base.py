import os


class _DontChangeMe:
    MAIN_ENV_PREFIX = "LLM_ROUTER_"


# Default ep language - e.g. for getting proper prompt
DEFAULT_EP_LANGUAGE = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}DEFAULT_EP_LANGUAGE", "pl"
).strip()


class BalanceStrategies:
    BALANCED = "balanced"
    WEIGHTED = "weighted"
    DYNAMIC_WEIGHTED = "dynamic_weighted"
    FIRST_AVAILABLE = "first_available"


POSSIBLE_BALANCE_STRATEGIES = [
    BalanceStrategies.BALANCED,
    BalanceStrategies.WEIGHTED,
    BalanceStrategies.DYNAMIC_WEIGHTED,
    BalanceStrategies.FIRST_AVAILABLE,
]
