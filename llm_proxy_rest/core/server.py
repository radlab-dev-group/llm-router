"""
Utility functions to launch the LLM Proxy REST API with various WSGI servers.

The module provides three convenience helpers:

* :func:`run_flask_server` – starts the API with Flask’s built‑in development
  server (useful for local testing).
* :func:`run_gunicorn_server` – runs the API with Gunicorn, offering
  production‑grade performance and streaming support.
* :func:`run_waitress_server` – runs the API with Waitress, a pure‑Python
  server that works well on Windows.

These helpers are used by ``rest_api.py`` to select the appropriate server
based on command‑line flags or the ``SERVER_TYPE`` configuration constant.
"""

from llm_proxy_rest.core.engine import FlaskEngine
from llm_proxy_rest.base.constants import (
    PROMPTS_DIR,
    MODELS_CONFIG_FILE,
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
            models_config_path=MODELS_CONFIG_FILE,
            logger_file_name=REST_API_LOG_FILE_NAME,
            logger_level=logger_level,
        ).prepare_flask_app().run(host=host, port=port, debug=debug)
    except RuntimeError as e:
        raise RuntimeError(f"Failed to run flask server: {e}")


def run_gunicorn_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    workers: int = 1,
    timeout: int = 0,
    log_level: str = "info",
):
    """
    Run the Flask app with Gunicorn
    (production-ready WSGI server with streaming support).
    """
    try:
        from gunicorn.app.base import BaseApplication
    except ImportError:
        raise ImportError(
            "Gunicorn is not installed. Install it with: pip install gunicorn"
        )

    class StandaloneApplication(BaseApplication):
        """
        Gunicorn ``BaseApplication`` wrapper for a Flask app.

        This subclass configures Gunicorn programmatically using the
        ``options`` dictionary supplied at initialization. It loads the
        Flask application provided via ``app`` and applies the given
        Gunicorn settings when ``run`` is invoked.
        """

        def __init__(self, app, options=None):
            self.options = options or {}
            self.application = app
            super().__init__()

        def load_config(self):
            for key, value in self.options.items():
                if key in self.cfg.settings and value is not None:
                    self.cfg.set(key.lower(), value)

        def load(self):
            return self.application

    logger_level_app = (
        "DEBUG" if log_level.lower() == "debug" else REST_API_LOG_LEVEL
    )

    app = FlaskEngine(
        prompts_dir=PROMPTS_DIR,
        models_config_path=MODELS_CONFIG_FILE,
        logger_file_name=REST_API_LOG_FILE_NAME,
        logger_level=logger_level_app,
    ).prepare_flask_app()

    options = {
        "bind": f"{host}:{port}",
        "workers": workers,
        "timeout": timeout,
        "loglevel": log_level,
        "worker_class": "gevent",
        "accesslog": "-",
        "errorlog": "-",
        "keepalive": 75,
    }

    StandaloneApplication(app, options).run()


def run_waitress_server(host: str = "0.0.0.0", port: int = 8080, threads: int = 4):
    """
    Run the Flask app with Waitress
    (pure-Python production server, Windows-friendly).

    Parameters
    ----------
    host : str, optional
        Interface address. Defaults to "0.0.0.0".
    port : int, optional
        TCP port. Defaults to 8080.
    threads : int, optional
        Number of threads for handling requests. Defaults to 4.

    Notes
    -----
    Requires Waitress installed: pip install waitress
    """
    try:
        from waitress import serve
    except ImportError:
        raise ImportError(
            "Waitress is not installed. Install it with: pip install waitress"
        )

    app = FlaskEngine(
        prompts_dir=PROMPTS_DIR,
        models_config_path=MODELS_CONFIG_FILE,
        logger_file_name=REST_API_LOG_FILE_NAME,
        logger_level=REST_API_LOG_LEVEL,
    ).prepare_flask_app()

    print(f"Starting Waitress server on {host}:{port} with {threads} threads...")
    serve(app, host=host, port=port, threads=threads, channel_timeout=300)
