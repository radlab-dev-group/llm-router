"""
Built-in ``LLM_ROUTER_*`` defaults used by the ``server`` subcommands.

The values mirror ``run-rest-api-gunicorn.sh`` so ``llm-router server start``
launches the REST API with the same configuration as the shell wrapper, while
:func:`apply_default_env` uses :func:`os.environ.setdefault` to keep the
user's shell (and every higher-precedence layer: ``config.env`` and CLI flags)
in charge.
"""

from __future__ import annotations

import os

from typing import Dict

from llm_router_lib.core.constants import ENV_PREFIX

#: Default of ``LLM_ROUTER_LOG_FILENAME`` — the application's *own* (rotating)
#: log file. It is a **relative** path, so it lands in the CWD (``./``), not in
#: ``~/.llm-router`` (that only holds the daemon's captured stdout/stderr).
DEFAULT_LOG_FILENAME = "llm-router.log"

#: ``LLM_ROUTER_*`` defaults mirrored from ``run-rest-api-gunicorn.sh``.
#: Applied with :func:`os.environ.setdefault`, so the user's shell always wins.
DEFAULT_ENV: Dict[str, str] = {
    # Logging
    "LLM_ROUTER_IN_DEBUG": "1",
    "LLM_ROUTER_VERBOSE": "0",
    "LLM_ROUTER_MINIMUM": "1",
    "LLM_ROUTER_LOG_FILENAME": DEFAULT_LOG_FILENAME,
    "LLM_ROUTER_LOG_TO_FILE": "1",
    "LLM_ROUTER_LOG_LEVEL": "INFO",
    "LLM_ROUTER_LOG_MAX_BYTES": "52428800",
    "LLM_ROUTER_LOG_BACKUP_COUNT": "5",
    # Metrics
    "LLM_ROUTER_USE_PROMETHEUS": "1",
    # Router resources
    "LLM_ROUTER_PROMPTS_DIR": "resources/prompts",
    "LLM_ROUTER_MODELS_CONFIG": "resources/configs/models-config.json",
    # Request limits
    "LLM_ROUTER_MAX_REQUEST_BODY_SIZE": "10485760",
    # Endpoints / routing
    "LLM_ROUTER_EP_PREFIX": "/api",
    "LLM_ROUTER_DEFAULT_EP_LANGUAGE": "pl",
    "LLM_ROUTER_BALANCE_STRATEGY": "balanced",
    # Server engine
    "LLM_ROUTER_SERVER_TYPE": "gunicorn",
    "LLM_ROUTER_SERVER_PORT": "8080",
    "LLM_ROUTER_SERVER_HOST": "0.0.0.0",
    "LLM_ROUTER_SERVER_WORKERS_COUNT": "4",
    "LLM_ROUTER_SERVER_THREADS_COUNT": "16",
    "LLM_ROUTER_SERVER_WORKER_CLASS": "",
    "LLM_ROUTER_TIMEOUT": "0",
    "LLM_ROUTER_EXTERNAL_TIMEOUT": "300",
    # Redis
    "LLM_ROUTER_REDIS_HOST": "",
    "LLM_ROUTER_REDIS_PORT": "6379",
    "LLM_ROUTER_REDIS_DB": "0",
    "LLM_ROUTER_REDIS_PASSWORD": "",
    "LLM_ROUTER_REDIS_PROTOCOL": "3",
    # Monitoring
    "LLM_ROUTER_SERVICES_MONITOR_INTERVAL_SECONDS": "5",
    "LLM_ROUTER_KEEPALIVE_MODEL_MONITOR_INTERVAL_SECONDS": "1",
    "LLM_ROUTER_PROVIDER_MONITOR_INTERVAL_SECONDS": "5",
    "LLM_ROUTER_PROVIDER_MONITOR_PING_TIMEOUT_SECONDS": "5.0",
    "LLM_ROUTER_PROVIDER_MONITOR_MAX_CONSECUTIVE_FAILURES": "2",
    # Masking
    "LLM_ROUTER_FORCE_MASKING": "0",
    "LLM_ROUTER_MASKING_WITH_AUDIT": "0",
    "LLM_ROUTER_MASKING_STRATEGY_PIPELINE": "fast_masker",
    # Guardrails
    "LLM_ROUTER_FORCE_GUARDRAIL_REQUEST": "0",
    "LLM_ROUTER_GUARDRAIL_WITH_AUDIT_REQUEST": "0",
    "LLM_ROUTER_GUARDRAIL_STRATEGY_PIPELINE_REQUEST": "",
    "LLM_ROUTER_GUARDRAIL_NASK_GUARD_HOST": "",
    "LLM_ROUTER_GUARDRAIL_SOJKA_GUARD_HOST": "",
    "LLM_ROUTER_MASKER_PII_HOST": "",
    # Authentication
    "LLM_ROUTER_AUTH_ENABLED": "false",
    "LLM_ROUTER_AUTH_KEY_STORE": "memory",
    "LLM_ROUTER_AUTH_MEMORY_SEED_FILE": "~/.llm-router/configs/auth/memory-keys.json",
    "LLM_ROUTER_AUTH_REDIS_HOST": "",
    "LLM_ROUTER_AUTH_REDIS_PORT": "6379",
    "LLM_ROUTER_AUTH_REDIS_DB": "0",
    "LLM_ROUTER_AUTH_REDIS_PASSWORD": "",
    "LLM_ROUTER_AUTH_REDIS_PROTOCOL": "3",
    "LLM_ROUTER_AUTH_VAULT_ADDR": "",
    "LLM_ROUTER_AUTH_VAULT_PATH": "secret/data/llm-router/api-keys",
    "LLM_ROUTER_AUTH_VAULT_AUTH_METHOD": "kubernetes",
    "LLM_ROUTER_AUTH_VAULT_ROLE_ID": "",
    "LLM_ROUTER_AUTH_VAULT_SECRET_ID": "",
    "LLM_ROUTER_AUTH_KEY_CACHE_TTL": "300",
    "LLM_ROUTER_AUTH_KEY_CACHE_JITTER": "60",
    "LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT": "60",
    "LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS": "/metrics,/health",
    "LLM_ROUTER_TRUSTED_PROXIES": "",
    "LLM_ROUTER_AUTH_FAILURE_LIMIT": "20",
    "LLM_ROUTER_AUTH_KEY_PREFIX": "sk-llmr-live",
    "LLM_ROUTER_AUTH_KEY_LENGTH": "48",
    "LLM_ROUTER_AUTH_ROTATION_GRACE_PERIOD": "3600",
    "LLM_ROUTER_AUTH_AUDIT": "",
    # Plugins / utils
    "LLM_ROUTER_UTILS_PLUGINS_PIPELINE": "",
    "LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_CONFIG": "",
    "LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_MODEL": "",
    "LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_TARGETS": "",
    "LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_CHUNK_SIZE": "",
    "LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_CHUNK_OVERLAP": "",
    "LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_PERSIST_DIR": "",
    "LLM_ROUTER_LANGCHAIN_RAG_COLLECTION": "",
    "LLM_ROUTER_LANGCHAIN_RAG_EMBEDDER": "",
    "LLM_ROUTER_LANGCHAIN_RAG_DEVICE": "cpu",
    "LLM_ROUTER_LANGCHAIN_RAG_CHUNK_SIZE": "1024",
    "LLM_ROUTER_LANGCHAIN_RAG_CHUNK_OVERLAP": "100",
    "LLM_ROUTER_LANGCHAIN_RAG_PERSIST_DIR": "",
    "TOKENIZERS_PARALLELISM": "true",
}


# -------------------------------------------------------------------------- #
# Applying the defaults, snapshotting the environment
# -------------------------------------------------------------------------- #
def apply_default_env() -> None:
    """Apply :data:`DEFAULT_ENV` without overriding variables already set."""
    for key, value in DEFAULT_ENV.items():
        os.environ.setdefault(key, value)


def collect_env() -> Dict[str, str]:
    """
    Snapshot every ``LLM_ROUTER_*`` variable currently set in the environment.

    Uses the shared :data:`ENV_PREFIX` from ``llm_router_lib.core.constants``
    so the run record always captures the full configuration the server was
    launched with (defaults + shell env + CLI overrides), not just the flags.
    Keys are returned sorted for stable, diffable records.
    """
    prefix = ENV_PREFIX
    return {
        key: value
        for key, value in sorted(os.environ.items())
        if key.startswith(prefix)
    }
