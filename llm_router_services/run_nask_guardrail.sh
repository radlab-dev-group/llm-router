#!/usr/bin/env bash
# ------------------------------------------------------------------
# Launch the NASK‑PIB Guardrail API using Gunicorn (2 workers)
# ------------------------------------------------------------------
# Required environment variables (can be overridden when invoking the script):
#   LLM_ROUTER_NASK_PIB_GUARD_FLASK_HOST – bind address (default: 0.0.0.0)
#   LLM_ROUTER_NASK_PIB_GUARD_FLASK_PORT – port (default: 5000)
#   LLM_ROUTER_NASK_PIB_GUARD_MODEL_PATH – model path / hub identifier
#   LLM_ROUTER_NASK_PIB_GUARD_DEVICE – device for the transformer pipeline
#                                           (-1 → CPU, 0/1 → GPU) (default: -1)
# ---------------------------------------------------------------

# Set defaults if they are not already defined in the environment
: "${LLM_ROUTER_NASK_PIB_GUARD_FLASK_HOST:=0.0.0.0}"
: "${LLM_ROUTER_NASK_PIB_GUARD_FLASK_PORT:=5000}"
: "${LLM_ROUTER_NASK_PIB_GUARD_MODEL_PATH:=NASK-PIB/HerBERT-PL-Guard}"
: "${LLM_ROUTER_NASK_PIB_GUARD_DEVICE:=0}"

#: "${LLM_ROUTER_NASK_PIB_GUARD_MODEL_PATH:=/mnt/data2/llms/models/community/NASK-PIB/HerBERT-PL-Guard}"

# Export them so the Python process can read them
export LLM_ROUTER_NASK_PIB_GUARD_FLASK_HOST
export LLM_ROUTER_NASK_PIB_GUARD_FLASK_PORT
export LLM_ROUTER_NASK_PIB_GUARD_MODEL_PATH
export LLM_ROUTER_NASK_PIB_GUARD_DEVICE

# Show the configuration that will be used
echo "Starting NASK‑PIB Guardrail API with Gunicorn (2 workers):"
echo "  HOST   = $LLM_ROUTER_NASK_PIB_GUARD_FLASK_HOST"
echo "  PORT   = $LLM_ROUTER_NASK_PIB_GUARD_FLASK_PORT"
echo "  MODEL  = $LLM_ROUTER_NASK_PIB_GUARD_MODEL_PATH"
echo "  DEVICE = $LLM_ROUTER_NASK_PIB_GUARD_DEVICE"
echo

# ---------------------------------------------------------------
# Run Gunicorn
#   -w 2               → 2 worker processes
#   -b host:port       → bind address
#   guardrails.nask_pib_guard_app:app  → import the Flask app object
# ---------------------------------------------------------------
gunicorn -w 1 -b \
  "${LLM_ROUTER_NASK_PIB_GUARD_FLASK_HOST}:${LLM_ROUTER_NASK_PIB_GUARD_FLASK_PORT}" \
  guardrails.nask.guard.nask_pib_guard_app:app