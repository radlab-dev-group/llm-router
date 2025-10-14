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

from typing import Optional

from llm_router_api.core.engine import FlaskEngine
from llm_router_api.base.constants import (
    PROMPTS_DIR,
    MODELS_CONFIG_FILE,
    REST_API_LOG_FILE_NAME,
    REST_API_LOG_LEVEL,
)


def run_flask_server(host: str, port: int, debug: bool = False):
    """
    Run the Flask development server for the LLM Proxy REST API.

    Parameters
    ----------
    host : str,
        Interface address to bind the server to.
    port : int,
        TCP port on which the server will listen to.
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
    host: str,
    port: int,
    workers: int = 2,
    threads: int = 8,
    timeout: int = 0,
    log_level: str = "info",
    worker_class: Optional[str] = None,
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
        "threads": threads,
        "timeout": timeout,
        "loglevel": log_level,
        "accesslog": "-",
        "errorlog": "-",
        "keepalive": 75,
    }

    if worker_class and len(worker_class.strip()):
        options["worker_class"] = worker_class

    StandaloneApplication(app, options).run()


def run_waitress_server(host: str, port: int, threads: int = 4):
    """
    Run the Flask app with Waitress
    (pure-Python production server, Windows-friendly).

    Parameters
    ----------
    host : str,
        Interface address.
    port : int,
        TCP port.
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
