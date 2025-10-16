import os


class _DontChangeMe:
    MAIN_ENV_PREFIX = "LLM_ROUTER_"


# Default ep language - e.g. for getting proper prompt
DEFAULT_EP_LANGUAGE = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}DEFAULT_EP_LANGUAGE", "pl"
).strip()
