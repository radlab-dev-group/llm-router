#!/bin/bash

set -e

# ==================================================================================
# General logging setup
export LLM_ROUTER_IN_DEBUG=${LLM_ROUTER_IN_DEBUG:-1}
export LLM_ROUTER_MINIMUM=${LLM_ROUTER_MINIMUM:-1}
export LLM_ROUTER_LOG_FILENAME=${LLM_ROUTER_LOG_FILENAME:-"llm-router.log"}

# ==================================================================================
# Metrics logging
export LLM_ROUTER_USE_PROMETHEUS=${LLM_ROUTER_USE_PROMETHEUS:-1}

# ==================================================================================
# Router resources
export LLM_ROUTER_PROMPTS_DIR=${LLM_ROUTER_PROMPTS_DIR:-"resources/prompts"}
export LLM_ROUTER_MODELS_CONFIG=${LLM_ROUTER_MODELS_CONFIG:-"resources/configs/models-config.json"}

# ==================================================================================
# Default endpoint prefix, language
export LLM_ROUTER_EP_PREFIX=${LLM_ROUTER_EP_PREFIX:-"/api"}
export LLM_ROUTER_DEFAULT_EP_LANGUAGE=${LLM_ROUTER_DEFAULT_EP_LANGUAGE:-"pl"}

# ==================================================================================
# Routing strategies: [balanced, weighted, first_available, first_available_optim]
export LLM_ROUTER_BALANCE_STRATEGY=${LLM_ROUTER_BALANCE_STRATEGY:-"first_available"}

# ==================================================================================
# Server engine configuration (flask, gunicorn, waitress)
export LLM_ROUTER_SERVER_TYPE=${LLM_ROUTER_SERVER_TYPE:-gunicorn}
export LLM_ROUTER_SERVER_PORT=${LLM_ROUTER_SERVER_PORT:-8080}
export LLM_ROUTER_SERVER_HOST=${LLM_ROUTER_SERVER_HOST:-"0.0.0.0"}
export LLM_ROUTER_SERVER_WORKERS_COUNT=${LLM_ROUTER_SERVER_WORKERS_COUNT:-4}
export LLM_ROUTER_SERVER_THREADS_COUNT=${LLM_ROUTER_SERVER_THREADS_COUNT:-16}
export LLM_ROUTER_SERVER_WORKER_CLASS=${LLM_ROUTER_SERVER_WORKER_CLASS:-""}
export LLM_ROUTER_TIMEOUT=${LLM_ROUTER_TIMEOUT:-0}
export LLM_ROUTER_EXTERNAL_TIMEOUT=${LLM_ROUTER_EXTERNAL_TIMEOUT:-300}

# ==================================================================================
# Redis configuration (used f.e. in fa_* strategies)
export LLM_ROUTER_REDIS_HOST=${LLM_ROUTER_REDIS_HOST:-"192.168.100.67"}
export LLM_ROUTER_REDIS_PORT=${LLM_ROUTER_REDIS_PORT:-6379}

# ==================================================================================
# LLM Router services monitoring (if any services will be used)
export LLM_ROUTER_SERVICES_MONITOR_INTERVAL_SECONDS=${LLM_ROUTER_SERVICES_MONITOR_INTERVAL_SECONDS:-5}
# Keep alive model monitor interval
export LLM_ROUTER_KEEPALIVE_MODEL_MONITOR_INTERVAL_SECONDS=${LLM_ROUTER_KEEPALIVE_MODEL_MONITOR_INTERVAL_SECONDS:-1}
# Models providers monitoring interval (in seconds)
export LLM_ROUTER_PROVIDER_MONITOR_INTERVAL_SECONDS=${LLM_ROUTER_PROVIDER_MONITOR_INTERVAL_SECONDS:-5}

# ==================================================================================
# Data protection (additional endpoints will be available)
# ------------ Masker section
export LLM_ROUTER_FORCE_MASKING=${LLM_ROUTER_FORCE_MASKING:-0}
export LLM_ROUTER_MASKING_WITH_AUDIT=${LLM_ROUTER_MASKING_WITH_AUDIT:-0}
export LLM_ROUTER_MASKING_STRATEGY_PIPELINE=${LLM_ROUTER_MASKING_STRATEGY_PIPELINE:-"fast_masker"}
# ------------ Guardrails section (request)
# Available guardrails types: [nask_guard, sojka_guard]
export LLM_ROUTER_FORCE_GUARDRAIL_REQUEST=${LLM_ROUTER_FORCE_GUARDRAIL_REQUEST:-0}
export LLM_ROUTER_GUARDRAIL_WITH_AUDIT_REQUEST=${LLM_ROUTER_GUARDRAIL_WITH_AUDIT_REQUEST:-0}
export LLM_ROUTER_GUARDRAIL_STRATEGY_PIPELINE_REQUEST=${LLM_ROUTER_GUARDRAIL_STRATEGY_PIPELINE_REQUEST:-"sojka_guard"}
# ------------ Guardrails section (response)
#export LLM_ROUTER_FORCE_GUARDRAIL_RESPONSE=${LLM_ROUTER_FORCE_GUARDRAIL_RESPONSE:-1}
#export LLM_ROUTER_GUARDRAIL_WITH_AUDIT_RESPONSE=${LLM_ROUTER_GUARDRAIL_WITH_AUDIT_RESPONSE:-1}
#export LLM_ROUTER_GUARDRAIL_STRATEGY_PIPELINE_RESPONSE=${LLM_ROUTER_GUARDRAIL_STRATEGY_PIPELINE_RESPONSE:-""}
# ------------ Guardrails services (host)
export LLM_ROUTER_GUARDRAIL_NASK_GUARD_HOST=${LLM_ROUTER_GUARDRAIL_NASK_GUARD_HOST:-"http://192.168.100.65:5000"}
export LLM_ROUTER_GUARDRAIL_SOJKA_GUARD_HOST=${LLM_ROUTER_GUARDRAIL_SOJKA_GUARD_HOST:-"http://192.168.100.65:5000"}

# ==================================================================================
# Utilities/plugins available: [langchain_rag]
#export LLM_ROUTER_UTILS_PLUGINS_PIPELINE=${LLM_ROUTER_UTILS_PLUGINS_PIPELINE:-""}
export LLM_ROUTER_UTILS_PLUGINS_PIPELINE=${LLM_ROUTER_UTILS_PLUGINS_PIPELINE:-"langchain_rag"}

# ------------ LangChainRAG Configuration
export LLM_ROUTER_LANGCHAIN_RAG_COLLECTION=${LLM_ROUTER_LANGCHAIN_RAG_COLLECTION:-"sample"}
export LLM_ROUTER_LANGCHAIN_RAG_EMBEDDER=${LLM_ROUTER_LANGCHAIN_RAG_EMBEDDER:-"/mnt/data2/llms/models/community/google/embeddinggemma-300m"}
export LLM_ROUTER_LANGCHAIN_RAG_DEVICE=${LLM_ROUTER_LANGCHAIN_RAG_DEVICE:-"cuda:1"}
export LLM_ROUTER_LANGCHAIN_RAG_CHUNK_SIZE=${LLM_ROUTER_LANGCHAIN_RAG_CHUNK_SIZE:-400}
export LLM_ROUTER_LANGCHAIN_RAG_CHUNK_OVERLAP=${LLM_ROUTER_LANGCHAIN_RAG_CHUNK_OVERLAP:-100}
export LLM_ROUTER_LANGCHAIN_RAG_PERSIST_DIR=${LLM_ROUTER_LANGCHAIN_RAG_PERSIST_DIR:"./workdir/plugins/utils/rag/langchain${LLM_ROUTER_LANGCHAIN_RAG_COLLECTION}"}

# ==================================================================================
# RUN MAIN APPLICATION
# ==================================================================================
exec python3 -m llm_router_api.rest_api
