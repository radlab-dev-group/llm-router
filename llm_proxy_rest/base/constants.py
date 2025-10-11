import os

from rdl_ml_utils.utils.env import bool_env_value


class _DontChangeMe:
    MAIN_ENV_PREFIX = "LLM_PROXY_API_"


# Directory with predefined system prompts
PROMPTS_DIR = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}PROMPTS_DIR", "resources/prompts"
).strip()

# Models config file
MODELS_CONFIG_FILE = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}MODELS_CONFIG",
    "resources/configs/models-config.json",
).strip()

# Default ep language - e.g. for getting proper prompt
DEFAULT_EP_LANGUAGE = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}DEFAULT_EP_LANGUAGE", "pl"
).strip()

# Timeout to external models api
REST_API_TIMEOUT = int(
    os.environ.get(f"{_DontChangeMe.MAIN_ENV_PREFIX}EXTERNAL_TIMEOUT", 300)
)

# Default name of a logging file
REST_API_LOG_FILE_NAME = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}LOG_FILENAME", "llm-proxy-rest.log"
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
        f"{_DontChangeMe.MAIN_ENV_PREFIX}SERVER_WORKERS_COUNT", "4"
    ).strip()
)

# Server host, default is 0.0.0.0
SERVER_HOST = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}SERVER_HOST", "0.0.0.0"
).strip()

# Run server in debug mode
RUN_IN_DEBUG_MODE = bool_env_value(f"{_DontChangeMe.MAIN_ENV_PREFIX}IN_DEBUG")
if RUN_IN_DEBUG_MODE:
    REST_API_LOG_LEVEL = "DEBUG"


def __verify_is_able_to_init():
    if not SERVICE_AS_PROXY:
        raise Exception(
            f"Currently llm-proxy-api only supports service-as-proxy mode!\n"
            f"Environment: {_DontChangeMe.MAIN_ENV_PREFIX}MINIMUM "
            f"must be set as True/1/yes/t\n\n"
            ">> LLM_PROXY_API_MINIMUM=1 python3 -m llm_proxy_rest.rest_api\n\n"
        )


__verify_is_able_to_init()
