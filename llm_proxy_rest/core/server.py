from llm_proxy_rest.core._engine import FlaskEngine
from llm_proxy_rest.base.constants import (
    PROMPTS_DIR,
    REST_API_LOG_FILE_NAME,
    REST_API_LOG_LEVEL,
)


def run_flask_server(host: str = "0.0.0.0", port: int = 8080, debug: bool = False):
    """
    Run the Flask development server for the LLM Proxy REST API.

    Parameters
    ----------
    host : str, optional
        Interface address to bind the server to. Defaults to ``"0.0.0.0"``.
    port : int, optional
        TCP port on which the server will listen to. Defaults to ``8080``.
    debug : bool, optional
        Enable Flask debug mode. Useful during development. Defaults to ``False``.

    The function creates the Flask application via `_prepare_flask_app`
    and starts it with the supplied configuration.
    """
    logger_level = "DEBUG" if debug else REST_API_LOG_LEVEL

    try:
        FlaskEngine(
            prompts_dir=PROMPTS_DIR,
            logger_file_name=REST_API_LOG_FILE_NAME,
            logger_level=logger_level,
        ).prepare_flask_app().run(host=host, port=port, debug=debug)
    except RuntimeError as e:
        raise RuntimeError(f"Failed to run flask server: {e}")
