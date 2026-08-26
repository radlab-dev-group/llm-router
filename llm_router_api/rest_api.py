"""
Entry point for launching the LLM Proxy REST server.

The script selects a WSGI server (Flask, Gunicorn or Waitress) based on
command‑line flags **or** the ``LLM_PROXY_API_SERVER`` environment variable.
It then starts the chosen server on ``0.0.0.0:8080`` (or the values
taken from ``llm_router_api.base.constants``).

Typical usage
---------------
>>> python -m rest_api --gunicorn      # production, streaming‑enabled
>>> python -m rest_api --waitress      # production, Windows‑friendly
>>> python -m rest_api                # development server (Flask)

"""

import logging
import argparse

from logging.handlers import RotatingFileHandler

from llm_router_api.core.server import (
    run_flask_server,
    run_gunicorn_server,
    run_waitress_server,
)
from llm_router_api.base.constants import (
    LOG_TO_FILE,
    LLM_ROUTER_API_TIMEOUT,
    REST_API_LOG_FILE_NAME,
    REST_API_LOG_LEVEL,
    REST_API_LOG_MAX_BYTES,
    REST_API_LOG_BACKUP_COUNT,
    SERVER_HOST,
    SERVER_PORT,
    SERVER_THREADS_COUNT,
    SERVER_TYPE,
    SERVER_WORKERS_CLASS,
    SERVER_WORKERS_COUNT,
)

logger = logging.getLogger(__name__)


def _setup_dual_logging():
    """Configure root logger to write to both console and file.

    FileHandler jest tworzony **tylko** gdy ``LLM_ROUTER_LOG_TO_FILE`` ma
    wartość true — inaczej logi idą wyłącznie na konsolę (StreamHandler).

    Flask.app.logger dostaje własny FileHandler z ``server.py``, bo moduł
    flask nie jest jeszcze zaimportowany w tym miejscu.
    """

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    root = logging.getLogger()
    if not root.handlers:  # unikaj duplikatów przy ponownym imporcie
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        root.addHandler(ch)

        # Conditionally add file handler.
        if LOG_TO_FILE:
            fh = RotatingFileHandler(
                REST_API_LOG_FILE_NAME,
                maxBytes=REST_API_LOG_MAX_BYTES,
                backupCount=REST_API_LOG_BACKUP_COUNT,
            )
            fh.setFormatter(fmt)
            root.addHandler(fh)

    log_level = getattr(logging, REST_API_LOG_LEVEL.upper(), logging.INFO)
    root.setLevel(log_level)


def _parse_args() -> argparse.Namespace:
    """
    Parse command‑line arguments.

    Returns
    -------
    argparse.Namespace
        Namespace with the parsed options; defaults are taken from the
        ``llm_router_api.base.constants`` module.
    """
    parser = argparse.ArgumentParser(
        description="Start LLM‑Router API with the chosen WSGI server"
    )
    parser.add_argument(
        "--gunicorn",
        action="store_true",
        help="Force using Gunicorn (production + streaming support)",
    )
    parser.add_argument(
        "--waitress",
        action="store_true",
        help="Force using Waitress (production, Windows‑friendly)",
    )
    parser.add_argument(
        "--host",
        default=SERVER_HOST,
        help="Interface to bind to (default: %(default)s)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=SERVER_PORT,
        help="Port number (default: %(default)s)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=SERVER_WORKERS_COUNT,
        help="Number of worker processes (Gunicorn only)",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=SERVER_THREADS_COUNT,
        help="Number of threads (Gunicorn/Waitress)",
    )
    return parser.parse_args()


def main() -> None:
    """
    Select the server backend and start it.

    The function is deliberately tiny so it can be imported and called from
    tests or other entry‑points.
    """
    args = _parse_args()

    # Choose server – CLI flags have priority over the ``SERVER_TYPE`` env variable.
    server_choice: str = (
        "gunicorn" if args.gunicorn else "waitress" if args.waitress else SERVER_TYPE
    )

    logger.info("Starting LLM‑Router API with %s", server_choice)

    try:
        if server_choice == "gunicorn":
            # Gunicorn → production‑grade workers + streaming support
            run_gunicorn_server(
                host=args.host,
                port=args.port,
                workers=args.workers,
                threads=args.threads,
                timeout=LLM_ROUTER_API_TIMEOUT,
                worker_class=SERVER_WORKERS_CLASS,
            )
        elif server_choice == "waitress":
            # Waitress → simple, Windows‑friendly server
            run_waitress_server(
                host=args.host,
                port=args.port,
                threads=args.workers,
            )
        else:
            # Flask → quick dev server (not recommended for production/streaming)
            run_flask_server(host=args.host, port=args.port, debug=False)
    except Exception:
        logger.exception("Failed to start the server")
        raise


if __name__ == "__main__":
    # Set up logging: console always, file only when LLM_ROUTER_LOG_TO_FILE=1.
    _setup_dual_logging()
    main()
