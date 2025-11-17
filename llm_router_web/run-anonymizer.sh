#!/usr/bin/env bash

# Start the llm‑router‑anonymizer-web project with gunicorn.
# It reads host, port and debug mode from environment variables
# prefixed with **LLM_ROUTER_WEB_ANO_** (HOST, PORT, DEBUG).
# If the variables are not set, the script falls back to the defaults
# used previously (host = 0.0.0.0, port = 8081, debug = true).

# -------------------------------------------------------------------------
# Read configuration from environment (with LLM_ROUTER_WEB_ prefix)
# -------------------------------------------------------------------------
#   LLM_ROUTER_WEB_ANO_HOST   – address to bind (default: 0.0.0.0)
#   LLM_ROUTER_WEB_ANO_PORT   – numeric port (default: 8082)
#   LLM_ROUTER_WEB_DEBUG  – truthy value enables Flask debug mode
# -------------------------------------------------------------------------
HOST="${LLM_ROUTER_WEB_ANO_HOST:-0.0.0.0}"
PORT="${LLM_ROUTER_WEB_ANO_PORT:-8082}"
DEBUG="${LLM_ROUTER_WEB_ANO_DEBUG:-true}"
ROUTER_HOST="${LLM_ROUTER_HOST:-"http://192.168.100.65:8080"}"
GENAI_MODEL_ANON="${LLM_ROUTER_HOST:-"gtp-oss:120b"}"

# -------------------------------------------------------------------------
# Export the variables so the Flask app (app.py) can read them.
export LLM_ROUTER_WEB_ANO_HOST="$HOST"
export LLM_ROUTER_WEB_ANO_PORT="$PORT"
export LLM_ROUTER_WEB_ANO_DEBUG="$DEBUG"
export LLM_ROUTER_HOST="$ROUTER_HOST"
export LLM_ROUTER_GENAI_MODEL_ANONYMISATION="$GENAI_MODEL_ANON"

# -------------------------------------------------------------------------
# Run the app with gunicorn.
#   -w 4           – number of worker processes (adjust as needed)
#   -b host:port   – bind address/port taken from the env vars above
# -------------------------------------------------------------------------
gunicorn --access-logfile - --error-logfile - --capture-output --enable-stdio-inheritance -w 1 -b "${HOST}:${PORT}" app_anonymizer:app
