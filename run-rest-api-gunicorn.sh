#!/bin/bash

set -e

# ==================================================================================
# General logging setup
# Debug mode (dont use on production, is really verbose)
export LLM_ROUTER_IN_DEBUG=${LLM_ROUTER_IN_DEBUG:-1}
# Verbose mode: logs RAW (unmasked) request params — PII! Dev only, never on production.
# The server waits a few seconds after printing a warning when it is enabled.
export LLM_ROUTER_VERBOSE=${LLM_ROUTER_VERBOSE:-0}
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
# Routing strategies: [balanced, weighted, first_available, first_available_optim, first_available_optim_nworkers]
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
# Worker slots of the first_available_optim_nworkers strategy (requires Redis)
# Lifetime [s] of a held worker slot. It must exceed the longest expected request
# (including streaming); a crashed process keeps its slots for this long.
export LLM_ROUTER_LB_SLOT_LEASE_SECONDS=${LLM_ROUTER_LB_SLOT_LEASE_SECONDS:-120}
# How long [s] an unreleased slot keeps being renewed. Covers a request that
# forgot its slot (an abandoned stream) - it is left to expire instead of
# occupying the provider until the router restarts. 0/negative disables the cap.
export LLM_ROUTER_LB_SLOT_MAX_AGE_SECONDS=${LLM_ROUTER_LB_SLOT_MAX_AGE_SECONDS:-1800}
# Lifetime [s] of the "this host serves this model" pin (first_available_optim*),
# refreshed on every selection. Only a host nothing has selected for this long
# becomes available to another model again.
export LLM_ROUTER_LB_HOST_PIN_TTL_SECONDS=${LLM_ROUTER_LB_HOST_PIN_TTL_SECONDS:-3600}

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
# Vault token (auth method "token"); never commit a real value here
export LLM_ROUTER_AUTH_VAULT_TOKEN=${LLM_ROUTER_AUTH_VAULT_TOKEN:-""}

# Custom authorization policies (JSON file); empty = builtin policies only
export LLM_ROUTER_AUTH_CUSTOM_POLICIES_FILE=${LLM_ROUTER_AUTH_CUSTOM_POLICIES_FILE:-""}

# Rate-limit presets file or directory used by `llm-router auth`; empty = packaged/builtin presets
export LLM_ROUTER_RATE_LIMITING_CONFIG=${LLM_ROUTER_RATE_LIMITING_CONFIG:-""}

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
export LLM_ROUTER_AUTH_KEY_PREFIX=${LLM_ROUTER_AUTH_KEY_PREFIX:-"sk-llmr-live"}
export LLM_ROUTER_AUTH_KEY_LENGTH=${LLM_ROUTER_AUTH_KEY_LENGTH:-48}

# Key rotation grace period (seconds)
export LLM_ROUTER_AUTH_ROTATION_GRACE_PERIOD=${LLM_ROUTER_AUTH_ROTATION_GRACE_PERIOD:-3600}

# Audit logging
export LLM_ROUTER_AUTH_AUDIT=${LLM_ROUTER_AUTH_AUDIT:-""}

# ==================================================================================
# Utilities/plugins available: [simple_semantic_routing,semantic_biencoder_routing,langchain_rag]
#export LLM_ROUTER_UTILS_PLUGINS_PIPELINE=${LLM_ROUTER_UTILS_PLUGINS_PIPELINE:-"simple_semantic_routing,langchain_rag"}
export LLM_ROUTER_UTILS_PLUGINS_PIPELINE=${LLM_ROUTER_UTILS_PLUGINS_PIPELINE:-""}

# ------------ Codex Agentic Routing Configuration (optional, requires the llm-router-plugins package)
# Activated by adding agentic_routing_codex to LLM_ROUTER_UTILS_PLUGINS_PIPELINE.
# Full variable list and defaults: llm_router_api/docs/ENV_DEFINITIONS.md
# (section: Codex Agentic Routing variables), detailed docs in the plugins repo
# (llm_router_plugins/utils/routing/agentic_routing/codex/README.md).
# Custom config: raw JSON string or path to a file (falls back to the bundled agentic_routing_codex.json)
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_CONFIG=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_CONFIG:-""}
# Trigger model value that activates the plugin (default auto_codex)
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_TRIGGER=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_TRIGGER:-"auto_codex"}
# Mode used when no other mode matches (default implement)
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_FALLBACK_MODE=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_FALLBACK_MODE:-"implement"}
# Embedding model identifier (HuggingFace / local path) for the semantic layer
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MODEL=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MODEL:-""}
# Toggle the embedding layer (1/0, true/false, yes/no, on/off)
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_SEMANTIC_ENABLED=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_SEMANTIC_ENABLED:-"true"}
# Minimum cosine similarity for a semantic hit
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_SIMILARITY_THRESHOLD=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_SIMILARITY_THRESHOLD:-""}
# Minimum keyword score to accept a heuristic hit
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_HEURISTIC_MIN_SCORE=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_HEURISTIC_MIN_SCORE:-""}
# Directory holding the persisted FAISS index + docstore (index.faiss, docstore.pkl)
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_PERSIST_DIR=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_PERSIST_DIR:-""}
# ------------ Codex Agentic Routing: shared session memory (optional, Redis-backed)
# Off by default. When enabled with the redis backend (default), REDIS_HOST below must be set;
# otherwise the plugin validates the connection with PING at startup, logs a warning and
# routing stays stateless. Connection settings are read ONLY from the plugin prefix and
# never from the generic LLM_ROUTER_REDIS_* or LLM_ROUTER_AUTH_REDIS_* variables.
# Turn the shared session memory on (default off)
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_ENABLED=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_ENABLED:-"false"}
# Memory backend: redis (production) or memory (tests/replay only)
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_BACKEND=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_BACKEND:-"redis"}
# Lifetime [s] of one session record (default 900)
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_TTL_SECONDS=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_TTL_SECONDS:-900}
# Sessions kept in this plugin namespace (default 10000)
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_MAX_SESSIONS=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_MAX_SESSIONS:-10000}
# Key namespace owned by the plugin (pruning never touches keys outside it)
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_KEY_PREFIX=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_KEY_PREFIX:-"llm-router:codex-routing"}
# Redis host of the session-memory store; empty = no connection, memory stays off
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_HOST=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_HOST:-""}
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_PORT=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_PORT:-6379}
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_DB=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_DB:-0}
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_PASSWORD=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_PASSWORD:-""}
# Redis protocol version (default: 3, RESP3)
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_PROTOCOL=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_PROTOCOL:-3}
# Optional ACL username for the session-memory Redis
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_USERNAME=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_USERNAME:-""}
# TLS: on/off (default off), cert verification: required (default), optional or none
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SSL=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SSL:-0}
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SSL_CERT_REQS=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SSL_CERT_REQS:-"required"}
# Paths to TLS material (CA bundle, client cert, client key) - used only when TLS is on
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SSL_CA_CERTS=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SSL_CA_CERTS:-""}
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SSL_CERTFILE=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SSL_CERTFILE:-""}
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SSL_KEYFILE=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SSL_KEYFILE:-""}
# Short positive timeouts [s] so a dead Redis cannot stall a routing decision (default 1.0)
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SOCKET_CONNECT_TIMEOUT=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SOCKET_CONNECT_TIMEOUT:-1.0}
export LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SOCKET_TIMEOUT=${LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SOCKET_TIMEOUT:-1.0}

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

YELLOW="\e[33m"
BLUE="\e[34m"
GREEN="\e[32m"
RESET="\e[0m"
# Instance name: LLM_ROUTER_INSTANCE wins, "localhost-dev" otherwise. It is
# exported so every child process and the log command see the same instance.
INSTANCE_NAME="${LLM_ROUTER_INSTANCE:-localhost-dev}"
export LLM_ROUTER_INSTANCE="${INSTANCE_NAME}"

function start_llm_router()
{
  printf '%bStarting LLMRouter server instance %b%s%b ' \
  "$YELLOW" "$BLUE" "$INSTANCE_NAME" "$RESET"
  printf "\n"

  llm-router server start -i "${INSTANCE_NAME}"
}

function show_llm_router_logs()
{
  for _ in {1..50}; do
    printf '%b*%b' "$GREEN" "$RESET"
    sleep 0.1
  done
  printf "\n"

  llm-router server log -i "${INSTANCE_NAME}"
}


start_llm_router

show_llm_router_logs
