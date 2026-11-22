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
| `LLM_ROUTER_VERBOSE`               | `False`                                | Log RAW, **unmasked** request params (PII!). Startup logs a warning and waits 3 s. Never use in production.      |
| `LLM_ROUTER_BALANCE_STRATEGY`      | `balanced`                             | Load-balancing strategy: `balanced`, `weighted`, `dynamic_weighted`, `first_available`, `first_available_optim`, `first_available_optim_nworkers`. |
| `LLM_ROUTER_LB_SLOT_LEASE_SECONDS` | `120`                                  | Lifetime of one held worker slot in `first_available_optim_nworkers`. Renewed while the router process lives, so it bounds how long a crashed process keeps occupying a provider. Must exceed the longest expected request only if the KeepAlive monitor cannot keep up. |
| `LLM_ROUTER_LB_SLOT_MAX_AGE_SECONDS` | `1800`                               | How long an unreleased worker slot keeps being renewed, counted from the acquisition. Covers a request that never released its slot (an abandoned stream): it is left to expire instead of occupying the provider until the router restarts. `0` or negative disables the cap. |
| `LLM_ROUTER_LB_HOST_PIN_TTL_SECONDS` | `3600`                               | Lifetime of the “this host serves this model” pin used by `first_available_optim` / `first_available_optim_nworkers` (Redis key `host:<host>`). Refreshed on every selection, so only a host nothing has selected for this long becomes available to another model. |
| `LLM_ROUTER_SERVER_TYPE`           | `flask`                                | Server implementation: flask, gunicorn, waitress.                                                                |
| `LLM_ROUTER_SERVER_PORT`           | `8080`                                 | Port on which the server listens.                                                                                |
| `LLM_ROUTER_SERVER_HOST`           | `localhost`                            | Host address for the server.                                                                                     |
| `LLM_ROUTER_SERVER_WORKERS_COUNT`  | `2`                                    | Number of workers (for servers that support them).                                                               |
| `LLM_ROUTER_SERVER_THREADS_COUNT`  | `8`                                    | Number of worker threads (for servers that support them).                                                        |
| `LLM_ROUTER_SERVER_WORKER_CLASS`   | `gthread` (for Gunicorn)               | Worker class for servers that support it (e.g. gevent). Defaults to `gthread` for Gunicorn: it honours `LLM_ROUTER_SERVER_THREADS_COUNT` and serves streaming responses, while the `sync` class Gunicorn would otherwise pick serves one request per worker at a time. |
| `LLM_ROUTER_HTTP_CONNECT_TIMEOUT`  | `5`                                    | Connect-phase timeout (seconds) for outbound provider calls. The read budget stays `LLM_ROUTER_EXTERNAL_TIMEOUT`, so a host that accepts the TCP connection and then stalls is still given the full read budget, while a host that never accepts a connection is dropped after this many seconds and failover can start. `0` disables the connect budget. |
| `LLM_ROUTER_HTTP_POOL_MAXSIZE`     | `32`                                   | Connections kept open per provider host by the shared outbound `requests.Session` (`llm_router_api/core/http_session.py`). Sized to cover the default worker thread count. |
| `LLM_ROUTER_HTTP_CONNECT_RETRIES`  | `1`                                    | Extra attempts for a provider call whose TCP connection was never established. Only a connection that was not established is retried, so a retried call can never have been executed by the provider; status and read retries are deliberately left to the provider failover, which re-dispatches to a different provider. |
| `LLM_ROUTER_NO_WARN_PROBE_RETRIES` | `False`                                | Probe health-check and keep-alive targets with a **single** connection attempt. A provider that is down answers every probe with `Connection refused`, and the connection retry above logs a urllib3 `Retrying ... after connection broken` warning per probe and per cycle. Setting this makes probes single-attempt, so the warning disappears: a probe measures one attempt, and `LLM_ROUTER_PROVIDER_MONITOR_MAX_CONSECUTIVE_FAILURES` already decides when a flapping host leaves the pool. The request path keeps its retry policy unchanged. CLI equivalent: `llm-router server start --no-warn-probe-retries`. |
| `LLM_ROUTER_SERVER_MAX_REQUESTS`   | `1000`                                 | Recycle a Gunicorn worker after this many requests to bound long-run memory growth. `0` disables recycling. |
| `LLM_ROUTER_SERVER_MAX_REQUESTS_JITTER` | `100`                                | Random offset (requests) added to `LLM_ROUTER_SERVER_MAX_REQUESTS` per worker, so a fleet does not recycle every worker at once. |
| `LLM_ROUTER_SERVER_GRACEFUL_TIMEOUT` | `LLM_ROUTER_EXTERNAL_TIMEOUT` (or `300`) | Seconds a recycled Gunicorn worker may spend finishing the requests it is already serving. Defaults to the outbound provider timeout, the longest a correctly-behaving request can take, so an in-flight generation — including a long stream — is never truncated by worker recycling. |
| `LLM_ROUTER_USE_PROMETHEUS`        | `False`                                | Enable Prometheus metrics collection (`/metrics` endpoint).                                                      |
| `LLM_ROUTER_INSTANCE`              | `default`                            | Name of the server instance the `llm-router server` subcommands manage (equivalent of `-i/--instance`); each named instance keeps its own state tree under `~/.llm-router/instances/<name>` (pid, run files, captured log). |

> See also `PROMETHEUS_MULTIPROC_DIR` for the directory where Prometheus multiprocess worker data files are stored.
> See also `TOKENIZERS_PARALLELISM` (Hugging Face `tokenizers`), set to `true` by the run scripts to silence the fork-safety warning when several gunicorn workers encode at once.

> **`LLM_ROUTER_VERBOSE` is a debugging aid, not a logging level.** With this variable on, `SecureEndpointI` stores it
> as `self._verbose_mode` and `run_ep` writes the **raw, unmasked** request payload (JSON) to the log *before* masking,
> so the log contains exactly the PII that masking would otherwise strip. On top of that, `rest_api.main()` logs a
> `WARNING` (console in the foreground, server/daemon log in the background) and sleeps 3 s
> (`VERBOSE_STARTUP_DELAY_SECONDS`) before the server binds its port, so an accidental
> production start can still be aborted. Enable it only for local troubleshooting (`LLM_ROUTER_VERBOSE=1`,
> `llm-router server start --verbose`) and never in production or on shared log storage.

## Google Vertex AI variables (optional)

Relevant only for providers with `api_type: "vertex_ai"` that do not carry an explicit
`api_token`; the router then resolves a Google access token through Application Default
Credentials (service-account JSON via `provider_options.credentials_file` or
`GOOGLE_APPLICATION_CREDENTIALS`, GCE/GKE metadata server, Workload Identity). This needs
the optional `google` dependency (`pip install "radlab-llm-router[google]"`, see
[`requirements-google.txt`](../../requirements-google.txt)).

| Variable                              | Default                                            | Description                                                                                          |
|---------------------------------------|----------------------------------------------------|------------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_GOOGLE_SCOPES`            | `https://www.googleapis.com/auth/cloud-platform`   | Comma‑separated OAuth2 scopes requested when resolving an access token.                              |
| `LLM_ROUTER_GOOGLE_TOKEN_REFRESH_SKEW`| `120`                                              | Seconds before expiry at which a cached access token is refreshed. A malformed value falls back to `120` instead of breaking start‑up. |

Token lifetime handling: `google-auth` reports `credentials.expiry` as a **naive
UTC** datetime, and the router reads it as UTC — so the cached lifetime no longer
shifts with the machine's timezone. Refreshes are serialised **per credential**
(a burst of concurrent requests mints one token, not one per request), and a
`401`/`403` from Vertex evicts the cached token so the next request mints a
fresh one rather than replaying a rejected credential until the process restarts.

---

## AWS Bedrock variables (optional)

Relevant only for providers with `api_type: "bedrock"` that carry neither an
`api_token` nor inline `provider_options` credentials — the router then signs
every request with SigV4 using credentials resolved from the environment or from
the AWS credential chain (shared config files and named profiles, SSO, assumed
IAM roles, EKS Web Identity / IRSA, the EC2/ECS metadata service). Signing, the
Converse translation and the event‑stream decoder need no dependency at all;
reaching the credential chain needs the optional `aws` dependency
(`pip install "radlab-llm-router[aws]"`, see
[`requirements-aws.txt`](../../requirements-aws.txt)) — a missing boto3 is
reported as a `RuntimeError` carrying the install hint.

Apart from the refresh skew below, these are the standard AWS variables, read as
they are.

| Variable                                        | Default             | Description                                                                                          |
|-------------------------------------------------|---------------------|------------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_AWS_TOKEN_REFRESH_SKEW`             | `300`               | Seconds before expiry at which cached chain‑resolved credentials (STS, IRSA, metadata service) are refreshed. A malformed value falls back to `300` instead of breaking start‑up. |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`   | *(empty)*           | Static credentials used when the provider carries none; a `provider_options` pair wins.              |
| `AWS_SESSION_TOKEN`                             | *(empty)*           | Session token of temporary static credentials.                                                       |
| `AWS_REGION` / `AWS_DEFAULT_REGION`             | *(empty)*           | Region used for signing and host derivation when `provider_options.region` is unset; the boto3 session region answers when neither is set. |
| `AWS_PROFILE`                                   | *(empty)*           | Named profile selected by the boto3 session and part of the credential cache key; `provider_options.profile` wins. |

Credential lifetime handling: expiring credentials are cached **per profile and
region**, refreshes are serialised **per key** (a burst of concurrent requests
resolves one credential, not one per request), and a `401`/`403` from Bedrock
evicts the cached credential so the next request resolves a fresh one rather
than replaying a rejected credential until the process restarts.

## Azure OpenAI variables (optional)

Relevant only for providers with `api_type: "azure_openai"` that carry neither
an `api_token` (Azure API key) nor an explicit
`provider_options.access_token`: the router then resolves a Microsoft Entra ID
bearer token itself.  No extra dependency is needed — the flows below use
`requests`, which the router already requires.

Resolution order: `provider_options` client credentials
(`tenant_id` / `client_id` / `client_secret`) → a workload identity federation
file → the App Service / Functions identity endpoint → the IMDS managed
identity of the Azure compute the router runs on.

| Variable                                        | Default                                              | Description                                                                                          |
|-------------------------------------------------|------------------------------------------------------|------------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_AZURE_TOKEN_REFRESH_SKEW`           | `120`                                                | Seconds before expiry at which a cached Entra ID token is refreshed. A malformed value falls back to `120` instead of breaking start‑up. |
| `LLM_ROUTER_AZURE_REQUEST_TIMEOUT`              | `10`                                                 | HTTP timeout (seconds) of the Entra ID token endpoint call.                                          |
| `LLM_ROUTER_AZURE_IDENTITY_TIMEOUT`             | `3`                                                  | HTTP timeout (seconds) of the link‑local identity calls (IMDS / App Service). Kept short: off Azure those endpoints are unreachable, and a long timeout would stall every request of a misconfigured provider. |
| `AZURE_TENANT_ID`                               | *(empty)*                                            | Tenant of the app registration / identity; `provider_options.tenant_id` wins.                        |
| `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET`       | *(empty)*                                            | Service‑principal credentials of the client‑credentials flow; `provider_options` wins.               |
| `AZURE_FEDERATED_TOKEN_FILE`                    | *(empty)*                                            | Workload identity federation assertion, as projected by AKS Workload Identity; `provider_options.federated_token_file` wins. |
| `AZURE_AUTHORITY_HOST`                          | `https://login.microsoftonline.com`                  | Entra authority host; set it for sovereign clouds (`provider_options.authority_host` wins).          |
| `AZURE_OPENAI_AD_SCOPE` / `AZURE_AD_SCOPE`      | `https://cognitiveservices.azure.com/.default`       | Audience requested for the token; `provider_options.scope` wins.                                     |
| `IDENTITY_ENDPOINT` + `IDENTITY_HEADER`         | *(empty)*                                            | App Service / Functions / Container Apps identity endpoint (legacy `MSI_ENDPOINT` + `MSI_SECRET` are read too). |

Credential lifetime handling: tokens are cached **per credential source**
(client id, tenant, scope, identity endpoint), refreshes are serialised
**per credential** (a burst of concurrent requests mints one token, not one
per request), and a `401`/`403` from Azure OpenAI evicts the cached token so
the next request mints a fresh one rather than replaying a rejected credential
until the process restarts.  When no source can mint a token the request fails
with a `RuntimeError` listing the sources it tried and, when one answered,
what it said (e.g. an `AADSTS…` diagnostic).

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

These variables are used **only by the router itself** (load balancing, provider availability, auth). Optional plugin components — e.g. the shared session memory of the `agentic_routing_codex` plugin — never inherit them: each has its own, explicitly prefixed connection variables (see the Codex Agentic Routing section below).

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

## Codex Agentic Routing variables

Requires the `llm-router-plugins` package. When `LLM_ROUTER_UTILS_PLUGINS_PIPELINE` includes `agentic_routing_codex`,
these variables configure the plugin. The plugin rewrites `payload["model"]` for requests that arrive with the
trigger model (`auto_codex` by default), based on a deterministic cascade (request class, collaboration mode, keyword
scoring) with an optional embedding-similarity layer; it never rejects a request and is fail-open on bad payloads.
Environment variables override the JSON config (raw JSON string or file path via `…_CONFIG`, otherwise the bundled
`agentic_routing_codex.json`) and are applied once at plugin construction. Precedence: ENV → JSON → default.

| Variable                                                          | Default            | Description                                                                                                                              |
|-------------------------------------------------------------------|--------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_CONFIG`                | *(empty)*          | Config source of truth — raw JSON string or file path. Falls back to the bundled `agentic_routing_codex.json`. No silent fall-through. |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_TRIGGER`               | *(empty)*          | Trigger model value that activates the plugin (bundled default `auto_codex`). Must exist in the models config as a `builtin` provider alias. |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MODEL_<MODE>`          | *(empty)*          | Model for one mode, e.g. `…_MODEL_TEST`.                                                                                                  |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MODELS`                | *(empty)*          | Per-mode models, e.g. `plan=model_a\|test=model_b`.                                                                                       |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MODES`                 | *(empty)*          | Pipe-separated whitelist of mode names to keep (if it excludes the fallback mode, set `…_FALLBACK_MODE` too). |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_FALLBACK_MODE`         | *(empty)*          | Mode used when nothing matches (bundled default `implement`).                                                                             |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_HEURISTIC_ENABLED`     | *(empty)*          | `1/0`, `true/false`, `yes/no`, `on/off` — toggle the keyword layer.                                                                        |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_HEURISTIC_MIN_SCORE`   | *(empty)*          | Minimum keyword score to accept a heuristic hit.                                                                                           |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_HEURISTIC_MIN_MARGIN`  | *(empty)*          | Minimum score lead over the runner-up (bundled default `1.0`; ties always continue to semantic/fallback).                                  |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_CLASSIFY_MAX_CHARS`    | *(empty)*          | Character budget of the classified user text (the newest message is always classified whole).                                              |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MODEL`                 | *(empty)*          | **Embedding** model identifier (HuggingFace / local path) for the semantic layer.                                                          |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_SEMANTIC_ENABLED`        | *(empty)*          | Toggle the embedding-similarity layer.                                                                                                     |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_SIMILARITY_THRESHOLD`  | *(empty)*          | Minimum cosine similarity for a semantic hit.                                                                                              |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_TOP_K` / `…_CHUNK_SIZE` / `…_CHUNK_OVERLAP` | *(empty)* | Embedding router knobs (per-target top-k count, token chunk size, token overlap).                     |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_PERSIST_DIR`           | *(empty)*          | Directory holding the persisted FAISS index + docstore (`index.faiss`, `docstore.pkl`).                                                    |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MODE_<name>_KEYWORDS`  | *(empty)*          | Pipe-separated keyword override for one mode.                                                                                              |

### Shared session memory (optional, Redis-backed)

Carries the last *reliable* work phase of the current command generation between successive requests of the same
session (session + thread + agent), so a neutral request in the middle of an action does not fall through to the
fallback. It is **off by default**, shared between Gunicorn workers through Redis (deliberately no local-process
cache), and stores no model names, conversation text, tool output or credentials. Memory is consulted only when the
deterministic layers stayed silent and never overrides a fresh, unambiguous signal. A memory error (Redis outage,
expired or damaged record) is a *miss*, never a failed request — routing continues stateless.

Policy variables (ENV → explicit JSON `settings.memory` → default):

| Variable                                                   | Default                    | Description                                                                          |
|------------------------------------------------------------|----------------------------|--------------------------------------------------------------------------------------|
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_ENABLED` | *(empty)* → **off**        | Turn the shared session memory on.                                                   |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_BACKEND` | *(empty)* → `redis`        | `redis` (production) or `memory` (isolated tests/replay only).                       |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_TTL_SECONDS` | *(empty)* → `900`       | Lifetime of one session record (seconds).                                            |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_MAX_SESSIONS` | *(empty)* → `10000`    | Cap on sessions kept in this plugin's namespace, enforced across workers.            |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_MAX_EVENTS` | *(empty)* → `64`       | Cap on remembered event identifiers per session.                                     |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_MAX_CALLS`  | *(empty)* → `32`       | Cap on remembered call identifiers per session.                                      |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_KEY_PREFIX` | *(empty)* → `llm-router:codex-routing` | Key namespace owned by the plugin; pruning never touches keys outside it.    |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_MAX_RETRIES` | *(empty)* → `1`        | Attempts after a version conflict before continuing statelessly.                     |

Connection variables — read **only** from the plugin prefix, never from the generic `LLM_ROUTER_REDIS_*` or the
`LLM_ROUTER_AUTH_REDIS_*` variables, and never from the JSON config (a config file cannot carry a Redis URL or
password). An empty host means *not configured*; with the `redis` backend and memory enabled, `REDIS_HOST` is
required — otherwise plugin construction fails with `CodexRouting: memory is enabled with the redis backend but …`. When memory
is enabled, the connection is checked with `PING` at startup; a failed check logs a warning (`Codex routing memory
disabled: …`) and routing stays stateless until the plugin is recreated.

| Variable                                                        | Default       | Description                                                                          |
|-----------------------------------------------------------------|---------------|--------------------------------------------------------------------------------------|
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_HOST`          | *(empty)*     | Session-memory Redis host. Empty = no connection, memory stays off.                  |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_PORT`          | `6379`        | Port.                                                                               |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_DB`            | `0`           | Database number (`0`–`15`).                                                         |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_PASSWORD`      | *(empty)*     | AUTH password; empty means no password.                                             |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_PROTOCOL`      | `3`           | RESP protocol version (`2` or `3`).                                                 |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_USERNAME`      | *(empty)*     | Optional ACL username.                                                              |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SSL`           | `0`           | TLS on/off. Enabling TLS never disables certificate verification silently.          |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SSL_CERT_REQS` | `required`    | TLS certificate verification: `required`, `optional` or `none`.                     |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SSL_CA_CERTS`  | *(empty)*     | Path to the CA bundle (used only when TLS is on).                                   |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SSL_CERTFILE`  | *(empty)*     | Path to the client certificate (used only when TLS is on).                          |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SSL_KEYFILE`   | *(empty)*     | Path to the client key (used only when TLS is on).                                  |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SOCKET_CONNECT_TIMEOUT` | `1.0` | Short connect timeout (seconds) so a dead Redis cannot stall a routing decision. |
| `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_REDIS_SOCKET_TIMEOUT`        | `1.0` | Short socket timeout (seconds).                                               |

The `redis` Python package is an optional dependency of the plugin; without it the plugin stays stateless. To reset the
plugin's memory: `redis-cli --scan --pattern '<MEMORY_KEY_PREFIX>*' | xargs redis-cli del` — that prefix only. The
decision annotation in `payload["routing"]` reports the memory outcome (`hit`, `miss`, `expired`, `conflict`, `unavailable`, …).

Full plugin documentation (decision cascade, work modes, tuning, troubleshooting):
[`llm_router_plugins/utils/routing/agentic_routing/codex/README.md`](https://github.com/radlab-dev-group/llm-router-plugins/blob/main/llm_router_plugins/utils/routing/agentic_routing/codex/README.md)
 in the `llm-router-plugins` repository.

Calibration and evaluation guides are alongside that README:
[CODEX_EVAL_HOWTO_PL.md (Polski)](https://github.com/radlab-dev-group/llm-router-plugins/blob/main/llm_router_plugins/utils/routing/agentic_routing/codex/CODEX_EVAL_HOWTO_PL.md)
and [CODEX_EVAL_HOWTO_EN.md (English)](https://github.com/radlab-dev-group/llm-router-plugins/blob/main/llm_router_plugins/utils/routing/agentic_routing/codex/CODEX_EVAL_HOWTO_EN.md).
They explain configuration roles, scores, embedding threshold/margin tuning, calibration/holdout datasets,
evaluation commands and metrics, and the plugins repository's `scripts/codex-tune-eval.sh` workflow.
The evaluation CLI reads the file passed via `--config`, **not production ENV overrides**, and uses isolated replay
memory rather than production Redis; save experimental parameters in that file before evaluating.

---

## Agentic Knowledge variables

Requires the `llm-router-plugins` package. When `LLM_ROUTER_UTILS_PLUGINS_PIPELINE` includes `agentic_knowledge`,
this knowledge layer runs behind the routing plugins: it retrieves verified fixes, dead ends, procedures and the
repository's own documentation from the Semantic Search Engine (SSE), injects a bounded block into coding-agent
requests, mines new knowledge out of the traffic, and can escalate a request stuck in a loop to a stronger model.
It is fail-open everywhere except the policy file, and idle with no engine host configured.

Precedence: ENV → policy JSON (`…_CONFIG`, raw JSON or a path; otherwise the bundled `agentic_knowledge.json`)
→ defaults below. Booleans accept `1/0`, `true/false`, `yes/no`, `on/off`. The full documentation (retrieval
behaviour, mining kinds, learning loop, CLI commands, troubleshooting) lives in
[`llm_router_plugins/utils/knowledge/agentic_knowledge/README.md`](https://github.com/radlab-dev-group/llm-router-plugins/blob/main/llm_router_plugins/utils/knowledge/agentic_knowledge/README.md)
in the `llm-router-plugins` repository.

### Switches and layout

| Variable                                                       | Default      | Description                                                                                                             |
|----------------------------------------------------------------|--------------|--------------------------------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_CONFIG`                          | *(empty)*    | Policy: raw JSON string or path to a policy file. Falls back to the bundled `agentic_knowledge.json`.                     |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_ENABLED`                         | `true`       | Master switch of the whole plugin.                                                                                        |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_READ_ENABLED`                    | `true`       | Knowledge injection on/off (mining may stay on).                                                                          |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_WRITE_ENABLED`                   | `true`       | Knowledge publishing on/off (injection may stay on).                                                                      |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_ARCHIVE_ENABLED`                 | `true`       | Archiving of the pre-compaction windows on/off.                                                                           |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_ESCALATION_ENABLED`              | `false`      | Model escalation on/off — a loop with no known-good recipe switches to a stronger model.                                  |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_LEARNING_ENABLED`                | `false`      | Learned path on/off: document reputation, the fitted ranking model, the source bandit. The training log is written either way; a model only reorders within a clamp and never overwrites the policy. |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_TASK_SOLUTIONS_ENABLED`          | `false`      | Mine a completed multi-file task that ran with no failure in between as a `task_solution` document.                       |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_TOOL_RECIPES_ENABLED`            | `false`      | Mine a verified single shell command as a `tool_recipe` document.                                                         |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_COLLECTION_PREFIX`               | `agentic_kb` | Prefix of every SSE collection owned by the plugin (letters/digits/`_`/`.`; reduced to an engine-safe fragment).          |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_COLLECTION_LAYOUT`               | `single`     | `single`: one collection per repository (`<prefix>_<scope>`), kinds told apart by engine category. `split`: the older three-collections spelling, for legacy indexes. |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_KEY_PREFIX`                      | `agentic-kb` | Redis key namespace owned by the plugin.                                                                                  |

### Semantic Search Engine (read side)

| Variable                                                       | Default  | Description                                                                                                              |
|----------------------------------------------------------------|----------|---------------------------------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_API_HOST`                    | *(empty)*| SSE host. **Empty ⇒ the layer is idle**: requests pass through with no knowledge.                                          |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_API_PREFIX`                  | *(empty)*| Engine API prefix; empty = the `sse_lib` client default.                                                                   |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_API_TOKEN`                   | *(empty)*| Engine token (never logged).                                                                                               |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_API_USERNAME`                | *(empty)*| Engine login for an engine that authenticates by user/password; a token, when set, wins. Never logged.                     |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_API_PASSWORD`                | *(empty)*| Engine login password.                                                                                                     |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_VERIFY`                      | `true`   | TLS certificate verification of the engine connection.                                                                     |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_API_TIMEOUT`                 | `2.0`    | Transport ceiling of one engine call in seconds, clamped to `0.1…60` (a clamp that bites logs a warning).                  |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_READ_TIMEOUT_SECONDS`            | `4.0`    | Read budget of the layer for one request in seconds, clamped to `0.1…60`; never smaller than the engine-call timeout.       |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_IGNORE_LANGUAGE_DETECT`      | `true`   | Ask the engine not to guess the query language (a guess filters the vector leg to it).                                     |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_MIN_SIMILARITY`                  | `0.35`   | Minimum similarity of a hit worth injecting.                                                                               |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_HYBRID_SEARCH`                   | `true`   | Fuse the vector leg with the full-text leg (Reciprocal Rank Fusion).                                                        |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_RERANK_RESULTS`                  | `true`   | Re-score retrieved chunks with the collection's cross-encoder; the score scale follows the reranker logit.                  |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_RERANK_WHEN_CONTESTED`           | `false`  | Re-ask a debug result whose top hits sit within `…_RERANK_CONTESTED_GAP` of each other through the cross-encoder before building the block; paid only when the fused ranks were not confident. |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_RERANK_CONTESTED_GAP`            | `0.05`   | Score spread of the top hits below which a search counts as contested.                                                      |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_RERANK_TOP_K`                    | `5`      | How many top hits the contested re-ask re-scores.                                                                           |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_FTS_ONLY_MIN_IDENTIFIER_SHARE`   | `0.5`    | A query whose tokens are mostly identifiers (exception class, dotted path, `::`-qualified name) is asked of the text index alone: no query embedding, no vector leg. `0` keeps every search on both legs. |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_CACHE_TTL_SECONDS`               | `3600`   | Lifetime in seconds of one generation's assembled context.                                                                  |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_MAX_LOOKUPS_PER_GENERATION`      | `20`     | Knowledge lookups per generation; per worker process when Redis is not configured.                                          |

### Escalation and feedback

| Variable                                                       | Default              | Description                                                                                       |
|----------------------------------------------------------------|----------------------|-----------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_LOOP_THRESHOLD`                  | `3`                  | Repetitions of one failure signature that make a loop.                                                 |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_STRONG_RECIPE_SCORE`             | `0.6`                | A recipe scoring at least this keeps the routed model instead of escalating (fallback for a scale unnamed in the table below). |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_STRONG_RECIPE_SCORES`            | `{"reranker": null}` | JSON map of the bound per retrieval scale (`cosine`, `rrf`, `reranker`, `""` for an unnamed one); `null` decides by identity — a signature match with a verification command counts without a score. |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_FEEDBACK_PUSH_INTERVAL_SECONDS`  | `60`                 | Minimum seconds between pushes of the settled verdicts to the engine feedback counters.                  |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_SUPERSEDE_AFTER_DAYS`            | `1`                  | A newer recipe retires the older one for the same file after this many days; `0` disables supersession.  |

### Event publishing (write side)

| Variable                                                  | Default  | Description                                                            |
|-----------------------------------------------------------|----------|---------------------------------------------------------------------------|
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_MAX_STREAM_LEN`             | `100000` | Length cap of the Redis event stream (`XADD MAXLEN ~`).                   |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_DEDUP_TTL_SECONDS`          | `604800` | Episode dedup window in seconds (7 days).                                 |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_MAX_PATCH_CHARS`            | `4000`   | Longest patch text admitted into one event.                               |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_ARCHIVE_MAX_CHUNK_CHARS`    | `2000`   | Size in characters of one archived window chunk.                          |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_ARCHIVE_TTL_SECONDS`        | `1209600`| Archive retention in seconds (14 days).                                   |

### Repository documentation

The repository's own `*.md` files are indexed as knowledge, and a standing map of them rides along
every session of the repository. The scan reads `repo_root` from the host the router runs on.

| Variable                                                  | Default   | Description                                                              |
|-----------------------------------------------------------|-----------|-----------------------------------------------------------------------------|
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_DOCS_ENABLED`               | `true`    | Documentation indexing on/off.                                             |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_DOCS_AUTO_INDEX`            | `true`    | A request may trigger a scan; `false` = only `llm-router-agentic-kb-docs` publishes. |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_DOCS_MAX_FILES`             | `200`     | Files read per scan; a scan that hits the ceiling prunes nothing.          |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_DOCS_MAX_FILE_BYTES`        | `200000`  | Largest documentation file read.                                           |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_DOCS_MAX_TOTAL_BYTES`       | `2000000` | Total bytes read per scan.                                                 |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_DOCS_RESCAN_INTERVAL_SECONDS` | `21600` | Seconds between scans of one repository.                                   |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_DOCS_STATE_TTL_SECONDS`     | `7776000` | Lifetime of a scope's scan state (90 days).                                |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_DOCS_CONTEXT_ENABLED`       | `true`    | The standing documentation map is injected with every session of a scope.  |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_DOCS_CONTEXT_MAX_CHARS`     | `700`     | Ceiling in characters of the map injected into a request.                  |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_DOCS_CONTEXT_TTL_SECONDS`   | `86400`   | How long a scope's map survives without a refresh.                         |

### Redis (event stream, cache, dedup)

Connection settings are read **only** from this prefix — never from `LLM_ROUTER_REDIS_*` or
`LLM_ROUTER_AUTH_REDIS_*`. No host = stateless mode: the plugin still reads, but with no cache and no writes.

| Variable                                                              | Default    | Description                                            |
|------------------------------------------------------------------------|------------|-----------------------------------------------------------|
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_REDIS_HOST`                              | *(empty)*  | **Empty ⇒ no writes, no cache** (stateless read-only mode). |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_REDIS_PORT`                              | `6379`     | Redis port.                                                |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_REDIS_DB`                                | `0`        | Redis database.                                            |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_REDIS_PASSWORD`                          | *(empty)*  | Redis password (never logged).                             |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_REDIS_PROTOCOL`                          | `3`        | RESP protocol; `3` needs Redis ≥ 6, use `2` against older. |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_REDIS_USERNAME`                          | *(empty)*  | Optional ACL username.                                     |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_REDIS_SSL`                               | `false`    | TLS on/off.                                                |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_REDIS_SSL_CERT_REQS`                     | `required` | Certificate verification: `required`, `optional`, `none`.  |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_REDIS_SSL_CA_CERTS`                      | *(empty)*  | CA bundle path (TLS only).                                 |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_REDIS_SSL_CERTFILE`                      | *(empty)*  | Client certificate path (TLS only).                        |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_REDIS_SSL_KEYFILE`                       | *(empty)*  | Client key path (TLS only).                                |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_REDIS_SOCKET_CONNECT_TIMEOUT`            | `1.0`      | Short connect timeout (s) so a dead Redis cannot stall a request. |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_REDIS_SOCKET_TIMEOUT`                    | `1.0`      | Short socket timeout (s).                                  |

### Indexing worker and CLIs (`llm-router-agentic-kb-*`)

Read by the indexing worker, the learner, the stats scoreboard and the docs publisher rather than by the server;
exported in the run scripts so both halves of the layer are configured in one place.

| Variable                                                  | Default             | Description                                       |
|-----------------------------------------------------------|---------------------|-------------------------------------------------------|
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_WORKER_GROUP`               | `agentic-kb`        | Consumer group the worker reads under.                 |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_WORKER_CONSUMER`            | *(empty)*           | Consumer name; empty = `worker-<timestamp>-<pid>`.     |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_WORKER_BATCH`               | `32`                | Events claimed per read.                               |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_WORKER_BLOCK_MS`            | `5000`              | How long a read waits for work.                        |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_MAX_PENDING`                | `1000`              | Pending length above which the worker warns.           |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_EMBEDDER`               | *(empty)*           | Embedder served by the engine; required to create a collection. |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_RERANKER`               | *(empty)*           | Reranker served by the engine; required to create a collection. |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_INDEX_TYPE`             | `HNSW`              | Vector index type of a new collection: `HNSW` or `IVF_FLAT`. |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_CHUNK_TOKENS`          | `400`               | Chunk size declared for a new collection; `0` = engine default (500). Applied at creation only. |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_SSE_CHUNK_OVERLAP`         | `60`                | Chunk overlap in tokens; must be smaller than the chunk size. |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_RETENTION_INTERVAL_SECONDS` | `21600`             | Seconds between retention passes; `0` disables them.   |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_CODEX_PHASE_CONFIG`         | *(empty)*           | Codex routing configuration the episode phase rules come from; empty = the bundled `agentic_routing_codex.json`. |

### Debug capture (dev only)

| Variable                                            | Default   | Description                                     |
|-----------------------------------------------------|-----------|----------------------------------------------------|
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_DEBUG_DUMP_DIR`       | *(empty)* | Directory receiving full request/tool-output dumps; empty = off. The dumps are **raw (unmasked)** — never point this at production storage. |
| `LLM_ROUTER_KNOWLEDGE_AGENTIC_DEBUG_DUMP_MAX`       | `50`      | How many capture files a directory keeps before the oldest is recycled. |

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
| `LLM_ROUTER_UTILS_PLUGINS_PIPELINE` | *(empty)* | Comma-separated list of utility plugins to apply (e.g. `simple_semantic_routing,langchain_rag,agentic_routing_codex`). |

Available plugins: `simple_semantic_routing`, `semantic_biencoder_routing`, `langchain_rag`, `agentic_routing_codex`, `agentic_routing_claude_code`, `agentic_knowledge`. Each plugin has additional configuration documented above.
configuration documented above.

---

## Authentication variables

### Core switch

| Variable                    | Default  | Description                                        |
|-----------------------------|----------|----------------------------------------------------|
| `LLM_ROUTER_AUTH_ENABLED`   | `false`  | Master switch — "true" enables all authentication. |
| `LLM_ROUTER_AUTH_KEY_STORE` | `memory` | Key store backend: vault, redis, or memory.        |

### Memory store

Seed file for the in-memory key store: `LLM_ROUTER_AUTH_MEMORY_SEED_FILE`, default
`${HOME}/.llm-router/configs/auth/memory-keys.json` (a JSON array of key records, for dev/test).
`constants.py` derives the path from `$HOME` and the CLI keeps this default in its managed env
file; renaming the file means moving it, not exporting a different path.

### Custom policies

| Variable                               | Default                                           | Description                                                                                                             |
|----------------------------------------|---------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_AUTH_CUSTOM_POLICIES_FILE` | `~/.llm-router/configs/auth/custom-policies.json` | JSON file with custom policies created via `llm-router auth policy create` (shared with the server at resolution time). |

### Vault settings

| Variable                            | Default                           | Description                                                    |
|-------------------------------------|-----------------------------------|----------------------------------------------------------------|
| `LLM_ROUTER_AUTH_VAULT_ADDR`        | *(empty)*                         | HashiCorp Vault server URL (e.g. `https://vault.example.com`). |
| `LLM_ROUTER_AUTH_VAULT_PATH`        | `secret/data/llm-router/api-keys` | KV v2 mount path for key storage.                              |
| `LLM_ROUTER_AUTH_VAULT_AUTH_METHOD` | `kubernetes`                      | Auth method: kubernetes, approle, or token.                    |
| `LLM_ROUTER_AUTH_VAULT_ROLE_ID`     | *(empty)*                         | AppRole role ID (or K8s SA token).                             |
| `LLM_ROUTER_AUTH_VAULT_SECRET_ID`   | *(empty)*                         | AppRole secret ID.                                             |
| `LLM_ROUTER_AUTH_VAULT_TOKEN`       | *(empty)*                         | Vault token, used with the `token` auth method. Required then; never store a real token in a committed file. |

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
| `LLM_ROUTER_RATE_LIMITING_CONFIG` | *(empty)* | Path to a rate-limit presets file or directory (`rate-limiting.json`) used by `llm-router auth`; empty falls back to the user config file, the packaged resource and the builtin presets. |

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

| Variable                     | Default        | Description                                              |
|------------------------------|----------------|----------------------------------------------------------|
| `LLM_ROUTER_AUTH_KEY_PREFIX` | `sk-llmr-live` | Key prefix (like LiteLLM/OpenAI format).                 |
| `LLM_ROUTER_AUTH_KEY_LENGTH` | `48`           | Entropy bytes for key generation (produces 64-char key). |

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
