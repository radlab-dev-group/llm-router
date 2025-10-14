#!/bin/bash

LLM_ROUTER_IN_DEBUG=0 \
  LLM_ROUTER_MINIMUM=1 \
  python3 -m llm_router_api.rest_api
