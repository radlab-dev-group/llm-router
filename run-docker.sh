#!/bin/bash

VERSION=rc1

PWD=$(pwd)
docker run \
  -p 5555:8080 \
  -e LLM_ROUTER_TIMEOUT=500 \
  -e LLM_ROUTER_IN_DEBUG=1 \
  -e LLM_ROUTER_MINIMUM=1 \
  -e LLM_ROUTER_EP_PREFIX="/api" \
  -e LLM_ROUTER_SERVER_TYPE=gunicorn \
  -e LLM_ROUTER_SERVER_PORT=8080 \
  -e LLM_ROUTER_SERVER_WORKERS_COUNT=4 \
  -e LLM_ROUTER_DEFAULT_EP_LANGUAGE="pl" \
  -e LLM_ROUTER_LOG_FILENAME="llm-router.log" \
  -e LLM_ROUTER_EXTERNAL_TIMEOUT=300 \
  -e LLM_ROUTER_MODELS_CONFIG=/srv/cfg.json \
  -e LLM_ROUTER_PROMPTS_DIR="/srv/prompts" \
  -v "${PWD}/resources/configs/models-config.json":/srv/cfg.json \
  -v "${PWD}/resources/prompts":/srv/prompts \
  quay.io/radlab/llm-router:${VERSION}
