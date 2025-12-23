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

from llm_router_api.core.server import (
    run_flask_server,
    run_gunicorn_server,
    run_waitress_server,
)
from llm_router_api.base.constants import (
    SERVER_TYPE,
    SERVER_PORT,
    SERVER_HOST,
    SERVER_WORKERS_COUNT,
    SERVER_THREADS_COUNT,
    SERVER_WORKERS_CLASS,
    LLM_ROUTER_API_TIMEOUT,
)

logger = logging.getLogger(__name__)


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
    # Basic logging configuration for the “script” execution path.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    main()
