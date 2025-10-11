#!/bin/bash

LLM_ROUTER_TIMEOUT=500 \
  LLM_ROUTER_IN_DEBUG=0 \
  LLM_ROUTER_MINIMUM=1 \
  python3 -m llm_proxy_rest.rest_api
