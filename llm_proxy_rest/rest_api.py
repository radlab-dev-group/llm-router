"""
Entry point for launching the LLM Proxy REST server.

Selects and starts the appropriate WSGI server (Flask, Gunicorn, or
Waitress) based on command‑line arguments or the ``LLM_PROXY_API_SERVER``
environment configuration. The server listens on ``0.0.0.0:8080``.
"""

import sys

from llm_proxy_rest.core.server import (
    run_flask_server,
    run_gunicorn_server,
    run_waitress_server,
)
from llm_proxy_rest.base.constants import SERVER_TYPE


if __name__ == "__main__":
    if "--gunicorn" in sys.argv or SERVER_TYPE == "gunicorn":
        print("Starting with Gunicorn (production + streaming support)...")
        run_gunicorn_server(host="0.0.0.0", port=8080, workers=1, timeout=0)
    elif "--waitress" in sys.argv or SERVER_TYPE == "waitress":
        print("Starting with Waitress (production, Windows-friendly)...")
        run_waitress_server(host="0.0.0.0", port=8080, threads=4)
    else:
        print("Starting with Flask dev server (NOT recommended for streaming)...")
        run_flask_server(host="0.0.0.0", port=8080, debug=False)
