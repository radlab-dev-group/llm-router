import os

from rdl_ml_utils.utils.env import bool_env_value

from llm_router_api.base.constants_base import (
    _DontChangeMe,
    DEFAULT_EP_LANGUAGE as _DEFAULT_EP_LANGUAGE,
    POSSIBLE_BALANCE_STRATEGIES,
    BalanceStrategies,
)


# Directory with predefined system prompts
PROMPTS_DIR = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}PROMPTS_DIR", "resources/prompts"
).strip()

# Models config file
MODELS_CONFIG_FILE = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}MODELS_CONFIG",
    "resources/configs/models-config.json",
).strip()

# # Default ep language - e.g. for getting proper prompt
DEFAULT_EP_LANGUAGE = _DEFAULT_EP_LANGUAGE

# Timeout to external models api
EXTERNAL_API_TIMEOUT = int(
    os.environ.get(f"{_DontChangeMe.MAIN_ENV_PREFIX}EXTERNAL_TIMEOUT", 300)
)

# Timeout to llm-router api
LLM_ROUTER_API_TIMEOUT = int(
    os.environ.get(f"{_DontChangeMe.MAIN_ENV_PREFIX}TIMEOUT", 0)
)

# Default name of a logging file
REST_API_LOG_FILE_NAME = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}LOG_FILENAME", "llm-router.log"
).strip()

# Default logging level
REST_API_LOG_LEVEL = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}LOG_LEVEL", "INFO"
).strip()

# Default prefix for each endpoint
DEFAULT_API_PREFIX = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}EP_PREFIX", "/api"
).strip()

# Run service as a proxy only
SERVICE_AS_PROXY = bool_env_value(f"{_DontChangeMe.MAIN_ENV_PREFIX}MINIMUM")

# Type of server, default is flask {flask, gunicorn, waitress}
SERVER_TYPE = (
    os.environ.get(f"{_DontChangeMe.MAIN_ENV_PREFIX}SERVER_TYPE", "flask")
    .lower()
    .strip()
)

# Server port, default is 8080
SERVER_PORT = int(
    os.environ.get(f"{_DontChangeMe.MAIN_ENV_PREFIX}SERVER_PORT", "8080").strip()
)

# Number of workers (if server supports multiple workers), default: 4
SERVER_WORKERS_COUNT = int(
    os.environ.get(
        f"{_DontChangeMe.MAIN_ENV_PREFIX}SERVER_WORKERS_COUNT", "2"
    ).strip()
)

# Number of threads (if server supports multithreading), default: 8
SERVER_THREADS_COUNT = int(
    os.environ.get(
        f"{_DontChangeMe.MAIN_ENV_PREFIX}SERVER_THREADS_COUNT", "8"
    ).strip()
)

# In some servers like gunicorn is able to set worker class (f.e. gevent)
SERVER_WORKERS_CLASS = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}SERVER_WORKER_CLASS", ""
).strip()

if not len(SERVER_WORKERS_CLASS):
    SERVER_WORKERS_CLASS = None

# Server host, default is 0.0.0.0
SERVER_HOST = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}SERVER_HOST", "0.0.0.0"
).strip()

# Run server in debug mode
RUN_IN_DEBUG_MODE = bool_env_value(f"{_DontChangeMe.MAIN_ENV_PREFIX}IN_DEBUG")
if RUN_IN_DEBUG_MODE:
    REST_API_LOG_LEVEL = "DEBUG"

# Use Prometheus to collect metrics
USE_PROMETHEUS = bool_env_value(f"{_DontChangeMe.MAIN_ENV_PREFIX}USE_PROMETHEUS")

# Strategy for load balancing when a multi-provider model is available
SERVER_BALANCE_STRATEGY = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}BALANCE_STRATEGY", BalanceStrategies.BALANCED
).strip()

# Strategy for load balancing when a multi-provider model is available
REDIS_HOST = os.environ.get(f"{_DontChangeMe.MAIN_ENV_PREFIX}REDIS_HOST", "").strip()

# Strategy for load balancing when a multi-provider model is available
REDIS_PORT = int(os.environ.get(f"{_DontChangeMe.MAIN_ENV_PREFIX}REDIS_PORT", 6379))


def __verify_is_able_to_init():
    if not SERVICE_AS_PROXY:
        raise Exception(
            f"Currently llm-proxy-api only supports service-as-proxy mode!\n"
            f"Environment: {_DontChangeMe.MAIN_ENV_PREFIX}MINIMUM "
            f"must be set as True/1/yes/t\n\n"
            ">> LLM_ROUTER_MINIMUM=1 python3 -m llm_router_api.rest_api\n\n"
        )


def __verify_correctness():
    if SERVER_BALANCE_STRATEGY not in POSSIBLE_BALANCE_STRATEGIES:
        raise Exception(
            f"{SERVER_BALANCE_STRATEGY} is not a valid strategy for balancing.\n"
            f"Available strategies: {POSSIBLE_BALANCE_STRATEGIES}"
        )


__verify_is_able_to_init()
__verify_correctness()
