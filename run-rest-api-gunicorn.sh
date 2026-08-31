#!/bin/bash

set -e

# ==================================================================================
# General logging setup
# Debug mode (dont use on production, is really verbose)
export LLM_ROUTER_IN_DEBUG=${LLM_ROUTER_IN_DEBUG:-1}
export LLM_ROUTER_MINIMUM=${LLM_ROUTER_MINIMUM:-1}
# Filename of logging (in case when log to file)
export LLM_ROUTER_LOG_FILENAME=${LLM_ROUTER_LOG_FILENAME:-"llm-router.log"}
# Also write logs to the log file (in addition to console)
export LLM_ROUTER_LOG_TO_FILE=${LLM_ROUTER_LOG_TO_FILE:-1}
# Logging level
export LLM_ROUTER_LOG_LEVEL=${LLM_ROUTER_LOG_LEVEL:-"INFO"}
# Log file rotation: rotate once the file reaches this size (bytes, default 50 MB)
export LLM_ROUTER_LOG_MAX_BYTES=${LLM_ROUTER_LOG_MAX_BYTES:-52428800}
# Maximum number of rotated log files to keep (llm-router.log.1 … llm-router.log.N)
export LLM_ROUTER_LOG_BACKUP_COUNT=${LLM_ROUTER_LOG_BACKUP_COUNT:-5}

# ==================================================================================
# Metrics logging
export LLM_ROUTER_USE_PROMETHEUS=${LLM_ROUTER_USE_PROMETHEUS:-1}

# ==================================================================================
# Router resources
export LLM_ROUTER_PROMPTS_DIR=${LLM_ROUTER_PROMPTS_DIR:-"resources/prompts"}
export LLM_ROUTER_MODELS_CONFIG=${LLM_ROUTER_MODELS_CONFIG:-"resources/configs/models-config.json"}

# ==================================================================================
# Request limits
# Maximum request body size in bytes (default: 10 MB, larger payloads -> 413)
export LLM_ROUTER_MAX_REQUEST_BODY_SIZE=${LLM_ROUTER_MAX_REQUEST_BODY_SIZE:-10485760}

# ==================================================================================
# Default endpoint prefix, language
export LLM_ROUTER_EP_PREFIX=${LLM_ROUTER_EP_PREFIX:-"/api"}
export LLM_ROUTER_DEFAULT_EP_LANGUAGE=${LLM_ROUTER_DEFAULT_EP_LANGUAGE:-"pl"}

# ==================================================================================
# Routing strategies: [balanced, weighted, first_available, first_available_optim]
export LLM_ROUTER_BALANCE_STRATEGY=${LLM_ROUTER_BALANCE_STRATEGY:-"balanced"}

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
export LLM_ROUTER_REDIS_HOST=${LLM_ROUTER_REDIS_HOST:-""}
export LLM_ROUTER_REDIS_PORT=${LLM_ROUTER_REDIS_PORT:-6379}
export LLM_ROUTER_REDIS_DB=${LLM_ROUTER_REDIS_DB:-0}
export LLM_ROUTER_REDIS_PASSWORD=${LLM_ROUTER_REDIS_PASSWORD:-""}
# Redis protocol version (default: 3, RESP3)
export LLM_ROUTER_REDIS_PROTOCOL=${LLM_ROUTER_REDIS_PROTOCOL:-3}

# ==================================================================================
# LLM Router services monitoring (if any services will be used)
export LLM_ROUTER_SERVICES_MONITOR_INTERVAL_SECONDS=${LLM_ROUTER_SERVICES_MONITOR_INTERVAL_SECONDS:-5}
# Keep alive model monitor interval
export LLM_ROUTER_KEEPALIVE_MODEL_MONITOR_INTERVAL_SECONDS=${LLM_ROUTER_KEEPALIVE_MODEL_MONITOR_INTERVAL_SECONDS:-1}
# Models providers monitoring interval (in seconds)
export LLM_ROUTER_PROVIDER_MONITOR_INTERVAL_SECONDS=${LLM_ROUTER_PROVIDER_MONITOR_INTERVAL_SECONDS:-5}
# Per-provider health-check ping timeout (seconds)
export LLM_ROUTER_PROVIDER_MONITOR_PING_TIMEOUT_SECONDS=${LLM_ROUTER_PROVIDER_MONITOR_PING_TIMEOUT_SECONDS:-5.0}
# Consecutive failed pings required before a provider is marked unavailable
export LLM_ROUTER_PROVIDER_MONITOR_MAX_CONSECUTIVE_FAILURES=${LLM_ROUTER_PROVIDER_MONITOR_MAX_CONSECUTIVE_FAILURES:-2}

# ==================================================================================
# Data protection (additional endpoints will be available)
# ------------ Masker section
export LLM_ROUTER_FORCE_MASKING=${LLM_ROUTER_FORCE_MASKING:-0}
export LLM_ROUTER_MASKING_WITH_AUDIT=${LLM_ROUTER_MASKING_WITH_AUDIT:-0}
#export LLM_ROUTER_MASKING_STRATEGY_PIPELINE=${LLM_ROUTER_MASKING_STRATEGY_PIPELINE:-"pii_masker,fast_masker"}
export LLM_ROUTER_MASKING_STRATEGY_PIPELINE=${LLM_ROUTER_MASKING_STRATEGY_PIPELINE:-"fast_masker"}
# ------------ Guardrails section (request)
# Available guardrails types: [nask_guard, sojka_guard]
export LLM_ROUTER_FORCE_GUARDRAIL_REQUEST=${LLM_ROUTER_FORCE_GUARDRAIL_REQUEST:-0}
export LLM_ROUTER_GUARDRAIL_WITH_AUDIT_REQUEST=${LLM_ROUTER_GUARDRAIL_WITH_AUDIT_REQUEST:-0}
export LLM_ROUTER_GUARDRAIL_STRATEGY_PIPELINE_REQUEST=${LLM_ROUTER_GUARDRAIL_STRATEGY_PIPELINE_REQUEST:-""}
# ------------ Guardrails section (response)
#export LLM_ROUTER_FORCE_GUARDRAIL_RESPONSE=${LLM_ROUTER_FORCE_GUARDRAIL_RESPONSE:-1}
#export LLM_ROUTER_GUARDRAIL_WITH_AUDIT_RESPONSE=${LLM_ROUTER_GUARDRAIL_WITH_AUDIT_RESPONSE:-1}
#export LLM_ROUTER_GUARDRAIL_STRATEGY_PIPELINE_RESPONSE=${LLM_ROUTER_GUARDRAIL_STRATEGY_PIPELINE_RESPONSE:-""}
# ------------ Guardrails and Maskers services (host)
# f.e. LLM_ROUTER_GUARDRAIL_NASK_GUARD_HOST=http://192.168.100.65:5000
export LLM_ROUTER_GUARDRAIL_NASK_GUARD_HOST=${LLM_ROUTER_GUARDRAIL_NASK_GUARD_HOST:-""}
# f.e. LLM_ROUTER_GUARDRAIL_SOJKA_GUARD_HOST=http://192.168.100.65:5000
export LLM_ROUTER_GUARDRAIL_SOJKA_GUARD_HOST=${LLM_ROUTER_GUARDRAIL_SOJKA_GUARD_HOST:-""}
# f.e. LLM_ROUTER_MASKER_PII_HOST=http://192.168.100.65:5000
export LLM_ROUTER_MASKER_PII_HOST=${LLM_ROUTER_MASKER_PII_HOST:-""}

# ==================================================================================
# Authentication
export LLM_ROUTER_AUTH_ENABLED=${LLM_ROUTER_AUTH_ENABLED:-false}

# Key store backend: vault | redis | memory
export LLM_ROUTER_AUTH_KEY_STORE=${LLM_ROUTER_AUTH_KEY_STORE:-"memory"}

# Memory store seed file (for dev/test with --store memory)
export LLM_ROUTER_AUTH_MEMORY_SEED_FILE=${LLM_ROUTER_AUTH_MEMORY_SEED_FILE:-"~/.llm-router/configs/auth/memory-keys.json"}

# Redis settings for auth key store (separate from LLM_ROUTER_REDIS_* used by keepalive/LB)
export LLM_ROUTER_AUTH_REDIS_HOST=${LLM_ROUTER_AUTH_REDIS_HOST:-""}
export LLM_ROUTER_AUTH_REDIS_PORT=${LLM_ROUTER_AUTH_REDIS_PORT:-6379}
export LLM_ROUTER_AUTH_REDIS_DB=${LLM_ROUTER_AUTH_REDIS_DB:-0}
export LLM_ROUTER_AUTH_REDIS_PASSWORD=${LLM_ROUTER_AUTH_REDIS_PASSWORD:-""}
export LLM_ROUTER_AUTH_REDIS_PROTOCOL=${LLM_ROUTER_AUTH_REDIS_PROTOCOL:-3}

# Vault settings (used when --store vault)
export LLM_ROUTER_AUTH_VAULT_ADDR=${LLM_ROUTER_AUTH_VAULT_ADDR:-""}
export LLM_ROUTER_AUTH_VAULT_PATH=${LLM_ROUTER_AUTH_VAULT_PATH:-"secret/data/llm-router/api-keys"}
export LLM_ROUTER_AUTH_VAULT_AUTH_METHOD=${LLM_ROUTER_AUTH_VAULT_AUTH_METHOD:-"kubernetes"}
export LLM_ROUTER_AUTH_VAULT_ROLE_ID=${LLM_ROUTER_AUTH_VAULT_ROLE_ID:-""}
export LLM_ROUTER_AUTH_VAULT_SECRET_ID=${LLM_ROUTER_AUTH_VAULT_SECRET_ID:-""}

# Redis cache for key lookups (used with any backend)
export LLM_ROUTER_AUTH_KEY_CACHE_TTL=${LLM_ROUTER_AUTH_KEY_CACHE_TTL:-300}
export LLM_ROUTER_AUTH_KEY_CACHE_JITTER=${LLM_ROUTER_AUTH_KEY_CACHE_JITTER:-60}

# Rate limiting
export LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT=${LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT:-60}

# Public endpoints (always bypass auth, comma-separated)
export LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS=${LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS:-"/metrics,/health"}

# Trusted reverse proxies (CSV of IPs/CIDRs); empty = X-Forwarded-For is always ignored
export LLM_ROUTER_TRUSTED_PROXIES=${LLM_ROUTER_TRUSTED_PROXIES:-""}
# Max failed-auth attempts per client IP per window before 429 lockout (0 disables)
export LLM_ROUTER_AUTH_FAILURE_LIMIT=${LLM_ROUTER_AUTH_FAILURE_LIMIT:-20}

# Key generation settings
export LLM_ROUTER_AUTH_KEY_PREFIX=${LLM_ROUTER_AUTH_KEY_PREFIX:-"sk-litm"}
export LLM_ROUTER_AUTH_KEY_LENGTH=${LLM_ROUTER_AUTH_KEY_LENGTH:-48}

# Key rotation grace period (seconds)
export LLM_ROUTER_AUTH_ROTATION_GRACE_PERIOD=${LLM_ROUTER_AUTH_ROTATION_GRACE_PERIOD:-3600}

# Audit logging
export LLM_ROUTER_AUTH_AUDIT=${LLM_ROUTER_AUTH_AUDIT:-""}

# ==================================================================================
# Utilities/plugins available: [simple_semantic_routing,semantic_biencoder_routing,langchain_rag]
#export LLM_ROUTER_UTILS_PLUGINS_PIPELINE=${LLM_ROUTER_UTILS_PLUGINS_PIPELINE:-"simple_semantic_routing,langchain_rag"}
export LLM_ROUTER_UTILS_PLUGINS_PIPELINE=${LLM_ROUTER_UTILS_PLUGINS_PIPELINE:-""}

# ------------ Semantic BiEncoder Routing Configuration
# Config source of truth: JSON file (via CONFIG env var).
# Individual env vars below can override settings from the JSON file.
# To use all values from the JSON file, leave these unset or empty.
export LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_CONFIG=${LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_CONFIG:-""}
# Embedding model identifier (HuggingFace / local path) — overrides JSON when set
export LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_MODEL=${LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_MODEL:-""}
# Pipe-separated list of target names (overrides all targets in config) — overrides JSON when set
export LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_TARGETS=${LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_TARGETS:-""}
# Token chunk size for embedding — overrides JSON when set
export LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_CHUNK_SIZE=${LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_CHUNK_SIZE:-}
# Token overlap between chunks — overrides JSON when set
export LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_CHUNK_OVERLAP=${LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_CHUNK_OVERLAP:-}
# Directory for FAISS index + docstore persistence (index.faiss, docstore.pkl) — overrides JSON when set
export LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_PERSIST_DIR=${LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_PERSIST_DIR:-""}

# ------------ LangChainRAG Configuration
# Sample local configuration:
#export LLM_ROUTER_LANGCHAIN_RAG_COLLECTION=${LLM_ROUTER_LANGCHAIN_RAG_COLLECTION:-"sample_collection"}
#export LLM_ROUTER_LANGCHAIN_RAG_EMBEDDER=${LLM_ROUTER_LANGCHAIN_RAG_EMBEDDER:-"google/embeddinggemma-300m"}
#export LLM_ROUTER_LANGCHAIN_RAG_DEVICE=${LLM_ROUTER_LANGCHAIN_RAG_DEVICE:-"cpu"}
#export LLM_ROUTER_LANGCHAIN_RAG_CHUNK_SIZE=${LLM_ROUTER_LANGCHAIN_RAG_CHUNK_SIZE:-1024}
#export LLM_ROUTER_LANGCHAIN_RAG_CHUNK_OVERLAP=${LLM_ROUTER_LANGCHAIN_RAG_CHUNK_OVERLAP:-100}
#export LLM_ROUTER_LANGCHAIN_RAG_PERSIST_DIR=${LLM_ROUTER_LANGCHAIN_RAG_PERSIST_DIR:-"./workdir/plugins/utils/rag/langchain/${LLM_ROUTER_LANGCHAIN_RAG_COLLECTION}"}
export LLM_ROUTER_LANGCHAIN_RAG_COLLECTION=${LLM_ROUTER_LANGCHAIN_RAG_COLLECTION:-""}
export LLM_ROUTER_LANGCHAIN_RAG_EMBEDDER=${LLM_ROUTER_LANGCHAIN_RAG_EMBEDDER:-""}
export LLM_ROUTER_LANGCHAIN_RAG_DEVICE=${LLM_ROUTER_LANGCHAIN_RAG_DEVICE:-"cpu"}
export LLM_ROUTER_LANGCHAIN_RAG_CHUNK_SIZE=${LLM_ROUTER_LANGCHAIN_RAG_CHUNK_SIZE:-1024}
export LLM_ROUTER_LANGCHAIN_RAG_CHUNK_OVERLAP=${LLM_ROUTER_LANGCHAIN_RAG_CHUNK_OVERLAP:-100}
export LLM_ROUTER_LANGCHAIN_RAG_PERSIST_DIR=${LLM_ROUTER_LANGCHAIN_RAG_PERSIST_DIR:-""}

# ==================================================================================
export TOKENIZERS_PARALLELISM=${TOKENIZERS_PARALLELISM:-true}

# ==================================================================================
# RUN MAIN APPLICATION
# ==================================================================================
exec python3 -m llm_router_api.rest_api
