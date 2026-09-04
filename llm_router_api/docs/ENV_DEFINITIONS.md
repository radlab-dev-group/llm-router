# Environment Variables

All environment variables share the `LLM_ROUTER_` prefix. They are loaded from `os.environ` in [
`llm_router_api/base/constants.py`](llm_router_api/base/constants.py) at import time and validated by
`_StartAppVerificator`.

---

## Core variables

| Variable                           | Default                                | Description                                                                                                      |
|------------------------------------|----------------------------------------|------------------------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_PROMPTS_DIR`           | `resources/prompts`                    | Directory containing predefined system prompts.                                                                  |
| `LLM_ROUTER_MODELS_CONFIG`         | `resources/configs/models-config.json` | Path to the models configuration JSON file.                                                                      |
| `LLM_ROUTER_DEFAULT_EP_LANGUAGE`   | `pl`                                   | Default language for endpoint prompts (fallback).                                                                |
| `LLM_ROUTER_TIMEOUT`               | `0`                                    | Timeout (seconds) for llm-router API calls.                                                                      |
| `LLM_ROUTER_EXTERNAL_TIMEOUT`      | `300`                                  | Timeout (seconds) for external model API calls.                                                                  |
| `LLM_ROUTER_MAX_REQUEST_BODY_SIZE` | `10485760` (10 MB)                     | Maximum request body size in bytes; oversized payloads get HTTP 413.                                             |
| `LLM_ROUTER_LOG_FILENAME`          | `llm-router.log`                       | Name of the log file.                                                                                            |
| `LLM_ROUTER_LOG_LEVEL`             | `INFO`                                 | Logging level (e.g. INFO, DEBUG).                                                                                |
| `LLM_ROUTER_LOG_TO_FILE`           | `false`                                | Also write logs to the log file (in addition to console).                                                        |
| `LLM_ROUTER_LOG_MAX_BYTES`         | `52428800` (50 MB)                     | Rotate the log file once it reaches this size in bytes (applied when `LLM_ROUTER_LOG_TO_FILE` is set).           |
| `LLM_ROUTER_LOG_BACKUP_COUNT`      | `5`                                    | Maximum number of rotated log files to keep, `<name>.1` … `<name>.N`.                                            |
| `LLM_ROUTER_EP_PREFIX`             | `/api`                                 | Prefix for all API endpoints.                                                                                    |
| `LLM_ROUTER_MINIMUM`               | `False`                                | Run service in proxy-only mode.                                                                                  |
| `LLM_ROUTER_IN_DEBUG`              | `False`                                | Run server in debug mode; also forces log level to DEBUG.                                                        |
| `LLM_ROUTER_BALANCE_STRATEGY`      | `balanced`                             | Load-balancing strategy: `balanced`, `weighted`, `dynamic_weighted`, `first_available`, `first_available_optim`. |
| `LLM_ROUTER_SERVER_TYPE`           | `flask`                                | Server implementation: flask, gunicorn, waitress.                                                                |
| `LLM_ROUTER_SERVER_PORT`           | `8080`                                 | Port on which the server listens.                                                                                |
| `LLM_ROUTER_SERVER_HOST`           | `localhost`                            | Host address for the server.                                                                                     |
| `LLM_ROUTER_SERVER_WORKERS_COUNT`  | `2`                                    | Number of workers (for servers that support them).                                                               |
| `LLM_ROUTER_SERVER_THREADS_COUNT`  | `8`                                    | Number of worker threads (for servers that support them).                                                        |
| `LLM_ROUTER_SERVER_WORKER_CLASS`   | `None`                                 | Worker class for servers that support it (e.g. gevent).                                                          |
| `LLM_ROUTER_USE_PROMETHEUS`        | `False`                                | Enable Prometheus metrics collection (`/metrics` endpoint).                                                      |

> See also `PROMETHEUS_MULTIPROC_DIR` for the directory where Prometheus multiprocess worker data files are stored.

---

## Redis variables

| Variable                    | Default   | Description                                                    |
|-----------------------------|-----------|----------------------------------------------------------------|
| `LLM_ROUTER_REDIS_HOST`     | *(empty)* | Redis host for load-balancing state and provider availability. |
| `LLM_ROUTER_REDIS_PORT`     | `6379`    | Redis port.                                                    |
| `LLM_ROUTER_REDIS_DB`       | `0`       | Redis database number.                                         |
| `LLM_ROUTER_REDIS_PASSWORD` | *(empty)* | Redis password.                                                |
| `LLM_ROUTER_REDIS_PROTOCOL` | `3`       | Redis protocol version (RESP2 = `2`, RESP3 = `3`).             |

When `LLM_ROUTER_REDIS_HOST` is set, the router uses Redis for load-balancing state and provider availability tracking.

---

## Masking & Guardrail variables

### Payload masking

| Variable                               | Default   | Description                                                                                              |
|----------------------------------------|-----------|----------------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_FORCE_MASKING`             | `False`   | Enable masking of every endpoint's payload before provider call.                                         |
| `LLM_ROUTER_MASKING_STRATEGY_PIPELINE` | *(empty)* | Comma-separated list of masker plugins (e.g. `fast_masker,pii_masker`).                                  |
| `LLM_ROUTER_MASKING_WITH_AUDIT`        | `False`   | Record each masking operation in the audit log.                                                          |
| `LLM_ROUTER_MASKER_PII_HOST`           | *(empty)* | Host URL of the remote ML-based `pii_masker` service. Must be set when using `pii_masker` in a pipeline. |

### Request guardrails

| Variable                                         | Default   | Description                                                                                                                  |
|--------------------------------------------------|-----------|------------------------------------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_FORCE_GUARDRAIL_REQUEST`             | `False`   | Force guardrail evaluation on every request.                                                                                 |
| `LLM_ROUTER_GUARDRAIL_WITH_AUDIT_REQUEST`        | `False`   | Audit all guardrail decisions for requests.                                                                                  |
| `LLM_ROUTER_GUARDRAIL_STRATEGY_PIPELINE_REQUEST` | *(empty)* | Comma-separated list of guardrail strategies (request).                                                                      |
| `LLM_ROUTER_GUARDRAIL_NASK_GUARD_HOST`           | *(empty)* | Host URL of the remote `nask_guard` service (HerBERT‑PL‑Guard, NASK‑PIB). Must be set when using `nask_guard` in a pipeline. |
| `LLM_ROUTER_GUARDRAIL_SOJKA_GUARD_HOST`          | *(empty)* | Host URL of the remote `sojka_guard` service (Bielik‑Guard). Must be set when using `sojka_guard` in a pipeline.             |

### Response guardrails

| Variable                                          | Default   | Description                                              |
|---------------------------------------------------|-----------|----------------------------------------------------------|
| `LLM_ROUTER_FORCE_GUARDRAIL_RESPONSE`             | `False`   | Force guardrail evaluation on every response.            |
| `LLM_ROUTER_GUARDRAIL_WITH_AUDIT_RESPONSE`        | `False`   | Audit all guardrail decisions for responses.             |
| `LLM_ROUTER_GUARDRAIL_STRATEGY_PIPELINE_RESPONSE` | *(empty)* | Comma-separated list of guardrail strategies (response). |

---

## Semantic BiEncoder Routing variables

Requires the `llm-router-plugins` package. When `LLM_ROUTER_UTILS_PLUGINS_PIPELINE` includes
`semantic_biencoder_routing`, these variables configure the plugin:

| Variable                                              | Default   | Description                                                                                                                                                                               |
|-------------------------------------------------------|-----------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_CONFIG`        | *(empty)* | Config source of truth — raw JSON string or file path. Falls back to bundled `semantic_biencoder.json`. Individual env vars below override loaded config values only when explicitly set. |
| `LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_MODEL`         | *(empty)* | Override the embedding model name or local path.                                                                                                                                          |
| `LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_TARGETS`       | *(empty)* | Pipe-separated list of target names (overrides all targets).                                                                                                                              |
| `LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_CHUNK_SIZE`    | *(empty)* | Token chunk size for embedding.                                                                                                                                                           |
| `LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_CHUNK_OVERLAP` | *(empty)* | Token overlap between consecutive chunks.                                                                                                                                                 |
| `LLM_ROUTER_ROUTING_SEMANTIC_BIENCODER_PERSIST_DIR`   | *(empty)* | Directory for FAISS index + docstore persistence (`index.faiss`, `docstore.pkl`).                                                                                                         |

---

## LangChainRAG variables

Requires the `llm-router-plugins` package. When `LLM_ROUTER_UTILS_PLUGINS_PIPELINE` includes `langchain_rag`, these
variables configure the RAG plugin:

| Variable                                 | Default   | Description                                                                                       |
|------------------------------------------|-----------|---------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_LANGCHAIN_RAG_COLLECTION`    | *(empty)* | Vector store collection name (required when langchain_rag is used).                               |
| `LLM_ROUTER_LANGCHAIN_RAG_EMBEDDER`      | *(empty)* | Path to the embedding model (e.g. `/mnt/data2/llms/models/community/google/embeddinggemma-300m`). |
| `LLM_ROUTER_LANGCHAIN_RAG_DEVICE`        | `cpu`     | Compute device for the embedding model (`cpu`, `cuda:0`, …).                                      |
| `LLM_ROUTER_LANGCHAIN_RAG_CHUNK_SIZE`    | *(empty)* | Chunk size for document splitting (required when langchain_rag is used).                          |
| `LLM_ROUTER_LANGCHAIN_RAG_CHUNK_OVERLAP` | *(empty)* | Overlap between consecutive chunks (required when langchain_rag is used).                         |
| `LLM_ROUTER_LANGCHAIN_RAG_PERSIST_DIR`   | *(empty)* | Directory for LangChainRAG index persistence.                                                     |

---

## Utils plugins variables

| Variable                            | Default   | Description                                                                                      |
|-------------------------------------|-----------|--------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_UTILS_PLUGINS_PIPELINE` | *(empty)* | Comma-separated list of utility plugins to apply (e.g. `simple_semantic_routing,langchain_rag`). |

Available plugins: `simple_semantic_routing`, `semantic_biencoder_routing`, `langchain_rag`. Each plugin has additional
configuration documented above.

---

## Authentication variables

### Core switch

| Variable                    | Default  | Description                                        |
|-----------------------------|----------|----------------------------------------------------|
| `LLM_ROUTER_AUTH_ENABLED`   | `false`  | Master switch — "true" enables all authentication. |
| `LLM_ROUTER_AUTH_KEY_STORE` | `memory` | Key store backend: vault, redis, or memory.        |

### Memory store

Seed file path (hardcoded): `${HOME}/.llm-router/configs/auth/memory-keys.json`

### Custom policies

| Variable                             | Default                                    | Description                                                                                     |
|--------------------------------------|--------------------------------------------|-------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_AUTH_CUSTOM_POLICIES_FILE` | `~/.llm-router/configs/auth/custom-policies.json` | JSON file with custom policies created via `llm-router auth policy create` (shared with the server at resolution time). |

### Vault settings

| Variable                            | Default                           | Description                                                    |
|-------------------------------------|-----------------------------------|----------------------------------------------------------------|
| `LLM_ROUTER_AUTH_VAULT_ADDR`        | *(empty)*                         | HashiCorp Vault server URL (e.g. `https://vault.example.com`). |
| `LLM_ROUTER_AUTH_VAULT_PATH`        | `secret/data/llm-router/api-keys` | KV v2 mount path for key storage.                              |
| `LLM_ROUTER_AUTH_VAULT_AUTH_METHOD` | `kubernetes`                      | Auth method: kubernetes, approle, or token.                    |
| `LLM_ROUTER_AUTH_VAULT_ROLE_ID`     | *(empty)*                         | AppRole role ID (or K8s SA token).                             |
| `LLM_ROUTER_AUTH_VAULT_SECRET_ID`   | *(empty)*                         | AppRole secret ID.                                             |

### Redis cache for keys

| Variable                           | Default | Description                              |
|------------------------------------|---------|------------------------------------------|
| `LLM_ROUTER_AUTH_KEY_CACHE_TTL`    | `300`   | Key cache TTL in seconds.                |
| `LLM_ROUTER_AUTH_KEY_CACHE_JITTER` | `60`    | Random jitter to prevent cache stampede. |

### Auth Redis (separate from general REDIS)

Auth-specific Redis connection used by the key store and rate limiter:

| Variable                         | Default   | Description                                             |
|----------------------------------|-----------|---------------------------------------------------------|
| `LLM_ROUTER_AUTH_REDIS_HOST`     | *(empty)* | Auth Redis host.                                        |
| `LLM_ROUTER_AUTH_REDIS_PORT`     | `6379`    | Auth Redis port.                                        |
| `LLM_ROUTER_AUTH_REDIS_DB`       | `0`       | Auth Redis database number.                             |
| `LLM_ROUTER_AUTH_REDIS_PASSWORD` | *(empty)* | Auth Redis password.                                    |
| `LLM_ROUTER_AUTH_REDIS_PROTOCOL` | `3`       | Auth Redis protocol version (RESP2 = `2`, RESP3 = `3`). |

### Rate limiting

Rate limiting is always applied when authentication is enabled:

| Variable                             | Default | Description                                                                                                                            |
|--------------------------------------|---------|----------------------------------------------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT` | `60`    | Default rate limit (requests per minute). Rate limiting is always active when authentication is enabled — there is no separate toggle. |

### Public endpoints

| Variable                           | Default            | Description                                       |
|------------------------------------|--------------------|---------------------------------------------------|
| `LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS` | `/health,/metrics` | Comma-separated paths that bypass authentication. |

### Hardening

| Variable                        | Default   | Description                                                                                                                                                                          |
|---------------------------------|-----------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_TRUSTED_PROXIES`    | *(empty)* | Comma-separated IPs/CIDRs of trusted proxies. Only a direct peer listed here may supply `X-Forwarded-For`; otherwise the header is ignored (anti-spoofing for rate-limit/IP checks). |
| `LLM_ROUTER_AUTH_FAILURE_LIMIT` | `20`      | Max failed-authentication attempts (missing/invalid key) per client IP per window before a `429` lockout. `0` disables the lockout.                                                  |

### Key generation

| Variable                     | Default   | Description                                              |
|------------------------------|-----------|----------------------------------------------------------|
| `LLM_ROUTER_AUTH_KEY_PREFIX` | `sk-litm` | Key prefix (like LiteLLM/OpenAI format).                 |
| `LLM_ROUTER_AUTH_KEY_LENGTH` | `48`      | Entropy bytes for key generation (produces 64-char key). |

### Key rotation

| Variable                                | Default | Description                                             |
|-----------------------------------------|---------|---------------------------------------------------------|
| `LLM_ROUTER_AUTH_ROTATION_GRACE_PERIOD` | `3600`  | Old keys remain valid this many seconds after rotation. |

### Audit

| Variable                | Default   | Description                          |
|-------------------------|-----------|--------------------------------------|
| `LLM_ROUTER_AUTH_AUDIT` | *(empty)* | Record auth events in the audit log. |

---

## Monitoring intervals

| Variable                                               | Default | Description                                                                                                                                                    |
|--------------------------------------------------------|---------|----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_SERVICES_MONITOR_INTERVAL_SECONDS`         | `5`     | Seconds between llm-router-services checks.                                                                                                                    |
| `LLM_ROUTER_KEEPALIVE_MODEL_MONITOR_INTERVAL_SECONDS`  | `1`     | Interval (seconds) for model keepalive check.                                                                                                                  |
| `LLM_ROUTER_PROVIDER_MONITOR_INTERVAL_SECONDS`         | `5`     | Seconds between next checks of models providers.                                                                                                               |
| `LLM_ROUTER_PROVIDER_MONITOR_PING_TIMEOUT_SECONDS`     | `5`     | Per-provider health-check ping timeout (seconds). Busy LLM hosts (e.g. Ollama serving a large model) may need more than 2 s to accept a new connection.        |
| `LLM_ROUTER_PROVIDER_MONITOR_MAX_CONSECUTIVE_FAILURES` | `2`     | Number of *consecutive* failed pings required before a provider is marked unavailable (hysteresis, prevents a single slow ping from removing a live provider). |

---

## Programmatic source

The definitive list of all runtime environment variables is in the source code: [
`llm_router_api/base/constants.py`](llm_router_api/base/constants.py). Each constant is loaded from `os.environ` with a
documented default and validated at import time.
