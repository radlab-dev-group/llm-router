import os

from rdl_ml_utils.utils.env import bool_env_value


class _DontChangeMe:
    MAIN_ENV_PREFIX = "LLM_PROXY_API_"


# Directory with predefined system prompts
PROMPTS_DIR = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}PROMPTS_DIR", "resources/prompts"
)

# Default name of a logging file
REST_API_LOG_FILE_NAME = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}LOG_FILENAME", "llm-proxy-rest.log"
)

# Default prefix for each endpoint
DEFAULT_API_PREFIX = os.environ.get(
    f"{_DontChangeMe.MAIN_ENV_PREFIX}EP_PREFIX", "/api"
)

# Run service as a proxy only
SERVICE_AS_PROXY = bool_env_value(f"{_DontChangeMe.MAIN_ENV_PREFIX}MINIMUM")

# Run server in debug mode
RUN_IN_DEBUG_MODE = bool_env_value(f"{_DontChangeMe.MAIN_ENV_PREFIX}IN_DEBUG")
