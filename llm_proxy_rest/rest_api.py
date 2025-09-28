from llm_proxy_rest.core.server import run_flask_server
from llm_proxy_rest.base.constants import RUN_IN_DEBUG_MODE


if __name__ == "__main__":
    run_flask_server(debug=RUN_IN_DEBUG_MODE)
