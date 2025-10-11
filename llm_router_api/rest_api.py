"""
Entry point for launching the LLM Proxy REST server.

Selects and starts the appropriate WSGI server (Flask, Gunicorn, or
Waitress) based on command‑line arguments or the ``LLM_PROXY_API_SERVER``
environment configuration. The server listens on ``0.0.0.0:8080``.
"""

import sys

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
)


if __name__ == "__main__":
    if "--gunicorn" in sys.argv or SERVER_TYPE == "gunicorn":
        print("Starting with Gunicorn (production + streaming support)...")
        run_gunicorn_server(
            host=SERVER_HOST,
            port=SERVER_PORT,
            workers=SERVER_WORKERS_COUNT,
            timeout=0,
        )
    elif "--waitress" in sys.argv or SERVER_TYPE == "waitress":
        print("Starting with Waitress (production, Windows-friendly)...")
        run_waitress_server(
            host=SERVER_HOST, port=SERVER_PORT, threads=SERVER_WORKERS_COUNT
        )
    else:
        print("Starting with Flask dev server (NOT recommended for streaming)...")
        run_flask_server(host=SERVER_HOST, port=SERVER_PORT, debug=False)
