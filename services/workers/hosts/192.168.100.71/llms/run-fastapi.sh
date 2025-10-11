#!/bin/bash

# The first argument is GPU -> may be useful for the future usage
# gpu="${1}"

port="${2}"
config_path="${3}"
service_workers_count=4

LLM_ROUTER_TIMEOUT=500 \
  LLM_ROUTER_IN_DEBUG=1 \
  LLM_ROUTER_MINIMUM=1 \
  LLM_ROUTER_PROMPTS_DIR="../resources/prompts" \
  LLM_ROUTER_MODELS_CONFIG="${config_path}" \
  LLM_ROUTER_LOG_FILENAME="llm-router.log" \
  LLM_ROUTER_EP_PREFIX="/api" \
  LLM_ROUTER_DEFAULT_EP_LANGUAGE="pl" \
  LLM_ROUTER_SERVER_TYPE=gunicorn \
  LLM_ROUTER_SERVER_PORT=${port} \
  LLM_ROUTER_SERVER_HOST="0.0.0.0" \
  LLM_ROUTER_SERVER_WORKERS=${service_workers_count} \
  LLM_ROUTER_EXTERNAL_TIMEOUT=300 \
  python3 -m llm_proxy_rest.rest_api
