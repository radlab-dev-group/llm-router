import os

from web.anonymizer import create_anonymize_app

# ----------------------------------------------
# Configuration – read from environment variables with the prefix
# LLM_ROUTER_WEB_ANO_*.  Fallback to the original defaults if not set.
# ----------------------------------------------
HOST = os.getenv("LLM_ROUTER_WEB_ANO_HOST", "0.0.0.0")
PORT = int(os.getenv("LLM_ROUTER_WEB_ANO_PORT", "8082"))

# DEBUG is expected to be a truthy string (e.g. "true", "1") or falsy.
_debug_val = os.getenv("LLM_ROUTER_WEB_ANO_DEBUG", "true").lower()
DEBUG = _debug_val in {"1", "true", "yes", "on"}

# Expose the Flask app as a module‑level variable for gunicorn.
app = create_anonymize_app()

if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=DEBUG)
