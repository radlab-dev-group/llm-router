import os

from rdl_ml_utils.utils.env import bool_env_value


class _DontChangeMe:
    MAIN_ENV_PREFIX = "LLM_PROXY_API_"


# Directory with predefined system prompts
PROMPTS_DIR = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}PROMPTS_DIR", "resources/prompts"
)

# Models config file
MODELS_CONFIG_FILE = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}PROMPTS_DIR",
    "resources/configs/models-config.json",
)

# Default ep language - e.g. for getting proper prompt
DEFAULT_EP_LANGUAGE = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}DEFAULT_EP_LANGUAGE", "pl"
)

# Timeout to external models api
REST_API_TIMEOUT = int(
    os.environ.get(f"{_DontChangeMe.MAIN_ENV_PREFIX}TIMEOUT", 300)
)

# Default name of a logging file
REST_API_LOG_FILE_NAME = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}LOG_FILENAME", "llm-proxy-rest.log"
)

# Default logging level
REST_API_LOG_LEVEL = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}LOG_LEVEL", "INFO"
)

# Default prefix for each endpoint
DEFAULT_API_PREFIX = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}EP_PREFIX", "/api"
)

# Run service as a proxy only
SERVICE_AS_PROXY = bool_env_value(f"{_DontChangeMe.MAIN_ENV_PREFIX}MINIMUM")


SERVER_TYPE = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}SERVER", "flask"
).lower()

# Run server in debug mode
RUN_IN_DEBUG_MODE = bool_env_value(f"{_DontChangeMe.MAIN_ENV_PREFIX}IN_DEBUG")
if RUN_IN_DEBUG_MODE:
    REST_API_LOG_LEVEL = "DEBUG"


def __verify_is_able_to_init():
    if not SERVICE_AS_PROXY:
        raise Exception(
            f"Currently llm-api-proxy only supports service-as-proxy mode!\n"
            f"Environment: {_DontChangeMe.MAIN_ENV_PREFIX}MINIMUM "
            f"must be set as True/1/yes/t\n\n"
            ">> LLM_PROXY_API_MINIMUM=1 python3 -m llm_proxy_rest.rest_api\n\n"
        )


__verify_is_able_to_init()
