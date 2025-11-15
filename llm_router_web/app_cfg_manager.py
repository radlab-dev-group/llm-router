import os

from web.configs_manager import create_config_manager_app

# ----------------------------------------------------------------------
# Configuration – read from environment variables with the prefix
# LLM_ROUTER_WEB_*.  Fallback to the original defaults if not set.
# ----------------------------------------------------------------------
HOST = os.getenv("LLM_ROUTER_WEB_HOST", "0.0.0.0")
PORT = int(os.getenv("LLM_ROUTER_WEB_PORT", "8081"))

# DEBUG is expected to be a truthy string (e.g. "true", "1") or falsy.
_debug_val = os.getenv("LLM_ROUTER_WEB_DEBUG", "true").lower()
DEBUG = _debug_val in {"1", "true", "yes", "on"}

# Expose the Flask app as a module‑level variable for gunicorn.
app = create_config_manager_app()

if __name__ == "__main__":
    # When run directly, start the built‑in development server using the
    # values obtained from the environment.
    app.run(host=HOST, port=PORT, debug=DEBUG)
