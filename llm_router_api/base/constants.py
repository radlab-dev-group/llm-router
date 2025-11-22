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

# Number of threads (if the server supports multithreading), default: 8
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

# =============================================================================
# MASKING
# =============================================================================
# If env is enabled, then a genai-based anonymization endpoint will be available
ENABLE_GENAI_ANONYMIZE_TEXT_EP = bool_env_value(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}ENABLE_GENAI_ANONYMIZE_TEXT_EP"
)
# If set to True, then each user request will be masked before the provider call
FORCE_MASKING = bool_env_value(f"{_DontChangeMe.MAIN_ENV_PREFIX}FORCE_MASKING")

# If True, then masking audit log will be handled
MASKING_WITH_AUDIT = bool_env_value(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}MASKING_WITH_AUDIT"
)

# Masking strategy pipeline in case when FORCE_MASKING
MASKING_STRATEGY_PIPELINE = str(
    os.environ.get(
        f"{_DontChangeMe.MAIN_ENV_PREFIX}MASKING_STRATEGY_PIPELINE", "fast_masker"
    )
)
if MASKING_STRATEGY_PIPELINE:
    MASKING_STRATEGY_PIPELINE = [
        _s.strip()
        for _s in MASKING_STRATEGY_PIPELINE.strip().split(",")
        if len(_s.strip())
    ]
# =============================================================================
# GUARDRAILS
# =============================================================================
# ----------- REQUEST GUARDRAIL
# If set to True, then each user request will be checked before the provider call
FORCE_GUARDRAIL_REQUEST = bool_env_value(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}FORCE_GUARDRAIL_REQUEST"
)

# If True, then guardrail audit log will be handled for each user request
GUARDRAIL_WITH_AUDIT_REQUEST = bool_env_value(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}GUARDRAIL_WITH_AUDIT_REQUEST"
)

# Guardrail strategy pipeline for request in case when FORCE_GUARDRAIL_REQUEST
GUARDRAIL_STRATEGY_PIPELINE_REQUEST = str(
    os.environ.get(
        f"{_DontChangeMe.MAIN_ENV_PREFIX}GUARDRAIL_STRATEGY_PIPELINE_REQUEST", ""
    )
)
if GUARDRAIL_STRATEGY_PIPELINE_REQUEST:
    GUARDRAIL_STRATEGY_PIPELINE_REQUEST = [
        _s.strip()
        for _s in GUARDRAIL_STRATEGY_PIPELINE_REQUEST.strip().split(",")
        if len(_s.strip())
    ]
# -----------------------------------------------------------------------------
# ----------- RESPONSE GUARDRAIL
# If set to True, then each response will be checked before receive response
FORCE_GUARDRAIL_RESPONSE = bool_env_value(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}FORCE_GUARDRAIL_RESPONSE"
)

# If True, then guardrail audit log will be handled for response
GUARDRAIL_WITH_AUDIT_RESPONSE = bool_env_value(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}GUARDRAIL_WITH_AUDIT_RESPONSE"
)

# Guardrail strategy pipeline for response in case when FORCE_GUARDRAIL_RESPONSE
GUARDRAIL_STRATEGY_PIPELINE_RESPONSE = str(
    os.environ.get(
        f"{_DontChangeMe.MAIN_ENV_PREFIX}GUARDRAIL_STRATEGY_PIPELINE_RESPONSE", ""
    )
)
if GUARDRAIL_STRATEGY_PIPELINE_RESPONSE:
    GUARDRAIL_STRATEGY_PIPELINE_RESPONSE = [
        _s.strip()
        for _s in GUARDRAIL_STRATEGY_PIPELINE_RESPONSE.strip().split(",")
        if len(_s.strip())
    ]

# =============================================================================
# ENVIRONMENTS USED INTO PLUGINS
# Host with router service where NASK-PIB/HerBERT-PL-Guard model is served
# Read model License before using this model **MODEL LICENSE** CC BY-NC-SA 4.0
GUARDRAIL_NASK_GUARD_HOST_EP = str(
    os.environ.get(
        f"{_DontChangeMe.MAIN_ENV_PREFIX}GUARDRAIL_NASK_GUARD_HOST_EP", ""
    )
)

# =============================================================================


class _StartAppVerificator:
    @staticmethod
    def __verify_is_able_to_init():
        if not SERVICE_AS_PROXY:
            raise Exception(
                f"Currently llm-proxy-api only supports service-as-proxy mode!\n"
                f"Environment: {_DontChangeMe.MAIN_ENV_PREFIX}MINIMUM "
                f"must be set as True/1/yes/t\n\n"
                ">> LLM_ROUTER_MINIMUM=1 python3 -m llm_router_api.rest_api\n\n"
            )

    @staticmethod
    def __verify_balancing_strategy():
        if SERVER_BALANCE_STRATEGY not in POSSIBLE_BALANCE_STRATEGIES:
            raise Exception(
                f"{SERVER_BALANCE_STRATEGY} is not a valid strategy for balancing.\n"
                f"Available strategies: {POSSIBLE_BALANCE_STRATEGIES}\n\n"
            )

    @staticmethod
    def __verify_default_masking_strategy():
        if MASKING_WITH_AUDIT:
            if not FORCE_MASKING:
                raise Exception(
                    f"`export LLM_ROUTER_FORCE_MASKING=1` environment is "
                    f"required when `LLM_ROUTER_MASKING_WITH_AUDIT=1`\n\n"
                )

        if FORCE_MASKING and not len(MASKING_STRATEGY_PIPELINE):
            raise Exception(
                "When FORCE_MASKING is set to `True`, you must specify the "
                "pipeline of masking strategies"
            )

    @staticmethod
    def __verify_default_request_guardrails():
        if GUARDRAIL_WITH_AUDIT_REQUEST:
            if not FORCE_GUARDRAIL_REQUEST:
                raise Exception(
                    f"`export LLM_ROUTER_FORCE_GUARDRAIL_REQUEST=1` environment is "
                    f"required when `LLM_ROUTER_GUARDRAIL_WITH_AUDIT_REQUEST=1`\n\n"
                )

        if FORCE_GUARDRAIL_REQUEST and not len(GUARDRAIL_STRATEGY_PIPELINE_REQUEST):
            raise Exception(
                "When FORCE_GUARDRAIL_REQUEST is set to `True`, you must specify the "
                "pipeline of guardrail strategies for each user request"
            )

    @staticmethod
    def __verify_default_response_guardrails():
        if GUARDRAIL_WITH_AUDIT_RESPONSE:
            if not FORCE_GUARDRAIL_RESPONSE:
                raise Exception(
                    f"`export LLM_ROUTER_FORCE_GUARDRAIL_RESPONSE=1` environment is "
                    f"required when `LLM_ROUTER_GUARDRAIL_WITH_AUDIT_RESPONSE=1`\n\n"
                )
        if FORCE_GUARDRAIL_RESPONSE and not len(
            GUARDRAIL_STRATEGY_PIPELINE_RESPONSE
        ):
            raise Exception(
                "When FORCE_GUARDRAIL_RESPONSE is set to `True`, you must specify the "
                "pipeline of guardrail strategies for each response"
            )

    def dont_run_if_something_is_wrong(self):
        self.__verify_is_able_to_init()
        self.__verify_balancing_strategy()
        self.__verify_default_masking_strategy()
        self.__verify_default_request_guardrails()
        self.__verify_default_response_guardrails()


_StartAppVerificator().dont_run_if_something_is_wrong()
