#!/bin/bash

# The first argument is GPU -> may be useful for the future usage
# gpu="${1}"

port="${2}"
config_path="${3}"
service_workers_count=4

LLM_PROXY_API_TIMEOUT=500 \
  LLM_PROXY_API_IN_DEBUG=1 \
  LLM_PROXY_API_MINIMUM=1 \
  LLM_PROXY_API_PROMPTS_DIR="../resources/prompts" \
  LLM_PROXY_API_MODELS_CONFIG="${config_path}" \
  LLM_PROXY_API_LOG_FILENAME="llm-proxy-rest.log" \
  LLM_PROXY_API_EP_PREFIX="/api" \
  LLM_PROXY_API_DEFAULT_EP_LANGUAGE="pl" \
  LLM_PROXY_API_SERVER_TYPE=gunicorn \
  LLM_PROXY_API_SERVER_PORT=${port} \
  LLM_PROXY_API_SERVER_HOST="0.0.0.0" \
  LLM_PROXY_API_SERVER_WORKERS=${service_workers_count} \
  LLM_PROXY_API_EXTERNAL_TIMEOUT=300 \
  python3 -m llm_proxy_rest.rest_api
