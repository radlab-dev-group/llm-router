#!/bin/bash

LLM_PROXY_API_TIMEOUT=500 \
  LLM_PROXY_API_IN_DEBUG=1 \
  LLM_PROXY_API_MINIMUM=1 \
  python3 -m llm_proxy_rest.rest_api
