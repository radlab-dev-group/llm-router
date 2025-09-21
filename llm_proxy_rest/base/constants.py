from llm_proxy_lib.utils.env import bool_env_value

# Run service as a proxy only
SERVICE_AS_PROXY = bool_env_value("LLM_PROXY_SERVICE_MINIMUM")
