# LLM Router - Open-Source AI Gateway for Local and Cloud LLM Infrastructure

[**LLM Router**](https://llm-router.cloud) is a service that can be deployed on‑premises or in the cloud. It adds a
layer between any application and the LLM provider. In real time it controls traffic, distributes load among providers
of a specific LLM, and enables analysis of outgoing requests from a security perspective (masking, anonymization,
prohibited content). It is an open‑source solution (Apache 2.0) that can be launched instantly by running a ready‑made
image in your own infrastructure.

---

## 🌐 Ecosystem Overview

The LLM‑Router project is split across five dedicated repositories:

| Repository                                                                          | Description                                                                                                                                                                                                            |
|-------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **[llm-router](https://github.com/radlab-dev-group/llm-router)** (this repo)        | Core gateway — unified REST proxy, Python SDK, and configuration management                                                                                                                                            |
| **[llm-router-api](https://github.com/radlab-dev-group/llm-router)** (subdirectory) | REST proxy that routes requests to any supported LLM backend (OpenAI‑compatible, Ollama, vLLM, LM Studio, Anthropic, Google Vertex AI, AWS Bedrock), with built‑in load‑balancing, health checks, streaming responses and optional Prometheus metrics |
| **[llm-router-lib](https://github.com/radlab-dev-group/llm-router)** (subdirectory) | Python SDK that wraps the API with typed request/response models, automatic retries, token handling, a rich exception hierarchy, and sync (`LLMRouterClient`) + async (`AsyncLLMRouterClient`, streaming) clients |
| **[llm-router-web](https://github.com/radlab-dev-group/llm-router-web)**            | Ready‑to‑use Flask UIs — a Config Manager for model/user settings and an Anonymizer UI that masks sensitive data                                                                                                       |
| **[llm-router-plugins](https://github.com/radlab-dev-group/llm-router-plugins)**    | Pluggable anonymizers (maskers), guardrails, semantic routing and RAG plugins                                                                                                                                          |
| **[llm-router-services](https://github.com/radlab-dev-group/llm-router-services)**  | HTTP services that power the plugin ecosystem (NASK‑PIB/Sojka guardrails, PII masker)                                                                                                                                  |
| **[llm-router-utils](https://github.com/radlab-dev-group/llm-router-utils)**        | CLI tools, batch translation, GenAI classification and ready‑made deployment configs (Speakleash models)                                                                                                               |

---

## ✨ Key Features

| Feature                             | Description                                                                                                                                                                                                                                 |
|-------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Unified REST interface**          | One endpoint schema works for OpenAI‑compatible, Ollama, vLLM, LM Studio and Anthropic.                                                                                                                                                     |
| **Provider‑agnostic streaming**     | The `stream` flag (default `true`) controls whether the proxy forwards **chunked** responses as they arrive or returns a **single** aggregated payload. Streaming responses include proper Cache‑Control, Pragma, Expires and Vary headers. |
| **Built‑in prompt library**         | Language‑aware system prompts stored under `resources/prompts` can be referenced automatically.                                                                                                                                             |
| **Dynamic model configuration**     | JSON file (`models-config.json`) defines providers, model name, default options and per‑model overrides.                                                                                                                                    |
| **Request validation**              | Pydantic models guarantee correct payloads; errors are returned with clear messages.                                                                                                                                                        |
| **Structured logging**              | Configurable log level, filename, and optional JSON formatting.                                                                                                                                                                             |
| **Health & metadata endpoints**     | `/health` and `/api/ping` (liveness), `/api/version` (build), `/models`, `/v1/models` and `/api/tags` (metadata), `/` for the Ollama probe.                                                                                                                                                                        |
| **Built‑in article generation**     | Two builtin endpoints were added: `/api/generate_article_from_texts` — generate a short (~A4) Polish article summarising a list of texts; and `/api/create_full_article_from_texts` — create a fuller article framed by `user_query`.       |
| **Embeddings support**              | Dedicated endpoints for generating text embeddings across all supported providers.                                                                                                                                                          |
| **Simple deployment**               | One‑liner run script, Docker image, or Helm chart for Kubernetes.                                                                                                                                                                           |
| **Extensible conversation formats** | Basic chat, conversation with system prompt, and extended conversation with richer options (temperature, top‑k, custom system prompt).                                                                                                      |
| **Multi‑provider model support**    | Each model can be backed by multiple providers (VLLM, Ollama, OpenAI, Anthropic, Google Vertex AI, AWS Bedrock) defined in `models-config.json`.                                                                                                      |
| **Model‑level fallback**            | A model can declare `fallback_model`: when none of its own providers can serve a request, the router reroutes it — before load balancing — to the fallback model, whose providers are balanced by the same strategy ([Models configuration](llm_router_api/docs/MODELS_CONFIG.md)). |
| **Provider failover**               | Any 4xx/5xx answer (or an unreachable provider) re-issues the request on the next provider of the same model — streaming included; only after every provider of the model was tried does `fallback_model` take over. |
| **Load‑balanced default strategy**  | `LoadBalancedStrategy` picks the least‑used provider; the usage counters live in Redis so every gunicorn worker and every replica shares them, degrading to in‑process counters when Redis is unavailable (`llm_router_api/core/lb/lb_counters.py`).                                                                                                                                         |
| **Dynamic model handling**          | `ModelHandler` loads model definitions at runtime and resolves the appropriate provider per request.                                                                                                                                        |
| **Pluggable endpoint architecture** | Automatic discovery and registration of all concrete `EndpointI` implementations via `EndpointAutoLoader`.                                                                                                                                  |
| **Prometheus metrics integration**  | Optional `/metrics` endpoint for latency, error counts, and provider usage statistics.                                                                                                                                                      |
| **Docker & Kubernetes ready**       | Dockerfile (non‑root user) and Helm charts for containerised deployment.                                                                                                                                                                    |

---

## 🧩 Plugin System Architecture

LLM Router uses a **registry-based pipeline pattern**. Each plugin implements a tiny, well‑defined `apply` method and
can be composed in an ordered list to form a pipeline. Pipelines are instantiated by the `MaskerPipeline`,
`GuardrailPipeline` and `UtilsPipeline` classes and are driven automatically by the endpoint logic in `endpoint_i.py`.

### Data flow

```
Request → MaskerPipeline → GuardrailPipeline → UtilsPipeline → Model Provider
```

### Masker Plugins

| Plugin ID         | Type          | Description                                                                                                                                                                 |
|-------------------|---------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **`fast_masker`** | Local         | Regex‑based PII masker with **30+ rule types** (emails, IPs, URLs, phone numbers, PESEL, NIP, KRS, REGON, monetary amounts, dates, credit cards, JWTs, passports and more). |
| **`pii_masker`**  | HTTP (remote) | ML‑based PII masker using a token‑classification model with an **in‑memory cache** to avoid redundant model calls for identical text inputs.                                |

### Guardrail Plugins

| Plugin ID         | Type          | Description                                                         |
|-------------------|---------------|---------------------------------------------------------------------|
| **`nask_guard`**  | HTTP (remote) | Safety check using the **HerBERT‑PL‑Guard** model (NASK‑PIB).       |
| **`sojka_guard`** | HTTP (remote) | Safety check using the **Bielik‑Guard‑0.1B** model from SpeakLeash. |

### Utility Plugins

| Plugin ID                        | Type  | Description                                                                                                                                                                                                                      |
|----------------------------------|-------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **`langchain_rag`**              | Local | Retrieves relevant document chunks from a FAISS vector store and injects them into the payload for Retrieval‑Augmented Generation.                                                                                               |
| **`simple_semantic_routing`**    | Local | Two‑stage heuristic model selection: intent classification + complexity analysis. Activated when `payload["model"] == "auto"`.                                                                                                   |
| **`semantic_biencoder_routing`** | Local | Embedding‑based semantic routing using FAISS — matches user messages against pre‑configured target embeddings to select the best model. See [Semantic BiEncoder Routing](#semantic-biencoder-routing) for configuration details. |
| **`agentic_routing_codex`**            | Local | Routing for **Codex CLI** requests: detects the work mode (plan, implement, test, git_review, review, debug, aux_title, compaction) of the `auto_codex` trigger and rewrites `payload["model"]` to the mode's model. Deterministic cascade with an optional embedding layer; optional **Redis‑backed shared session memory** keeps the reliable phase between calls of one action. See [Codex Agentic Routing](#codex-agentic-routing) for details. |
| **`agentic_routing_claude_code`**        | Local | Model swap for **Claude Code**: maps the versioned model IDs Claude Code sends (resolved from `opus` / `sonnet` / `haiku` / `fable` tiers) onto the models you serve them with. |

Pipelines are configured via environment variables:

```bash
# Comma-separated list of masker plugins to apply
export LLM_ROUTER_MASKING_STRATEGY_PIPELINE="fast_masker,pii_masker"

# Enable guardrails
export LLM_ROUTER_FORCE_GUARDRAIL_REQUEST=1

# Enable masking entirely
export LLM_ROUTER_FORCE_MASKING=1

# Record masking operations in audit log
export LLM_ROUTER_MASKING_WITH_AUDIT=1
```

### Semantic BiEncoder Routing

The `semantic_biencoder_routing` plugin uses a neural embedding model (**google/embeddinggemma-300m**) to compute
semantic embeddings for a set of pre‑configured routing targets. Each target has a `name`, a `model_name` (the model to
route to), a `description`, and a list of `examples`. At query time the user message is embedded and matched against all
stored target embeddings using FAISS (`IndexFlatIP` on L2‑normalised vectors = cosine similarity). The best‑matching
target determines the selected model.

#### How it works

**1. Index building (on first load or when the persist directory is missing):**

- For each routing target, its `description` and `examples` are combined into text.
- The text is split into overlapping **token chunks** using a sliding window (`chunk_size` tokens, `chunk_overlap`
  tokens overlap).
- Each chunk is embedded via the BiEncoder model (e.g. `google/embeddinggemma-300m`).
- All embedding vectors are **L2‑normalised** to unit length.
- Vectors are inserted into a `faiss.IndexFlatIP` index (inner product).
- A docstore maps each FAISS document ID to its target name (for reverse lookup).

**2. Routing (query):**

- The user message is embedded and L2‑normalised.
- FAISS performs a nearest‑neighbor search returning the `top_k` closest chunks.
- Scores are **aggregated per target**: the mean cosine similarity of all chunks belonging to the same target is
  computed.
- The target with the **highest mean similarity** wins and its `model_name` is returned.

**3. Persistence:**

The FAISS index and docstore are saved to disk (files `index.faiss` and `docstore.pkl`) under the configured persist
directory. On subsequent starts the index is loaded from disk — embeddings are **not recomputed**. If the embedding
model changes (different output dimension) the index is automatically rebuilt.

Full example JSON config with `routing_targets` and their `examples` is available in the plugins repo:
[`llm_router_plugins/resources/routing/semantic_biencoder.json`](
https://github.com/radlab-dev-group/llm-router-plugins/blob/main/llm_router_plugins/resources/routing/semantic_biencoder.json
). Detailed variable descriptions and usage examples:
[Plugin Routing README](
https://github.com/radlab-dev-group/llm-router-plugins/blob/main/llm_router_plugins/utils/routing/README.md#24-configuration
).

**Example routing targets:**

| Target name         | Model routed to | Description                                                              |
|---------------------|-----------------|--------------------------------------------------------------------------|
| `code-generation`   | `qwen3.6:35b`   | Code‑related tasks: writing, debugging, refactoring.                     |
| `math-analysis`     | `qwen3.6:35b`   | Mathematical computations, statistical analysis, quantitative reasoning. |
| `creative-writing`  | `gpt-oss:120b`  | Creative and generative writing: stories, poems, marketing content.      |
| `general-assistant` | `gpt-oss:120b`  | Everyday questions, explanations, research, conversation.                |
| `data-science`      | `qwen3.6:35b`   | Data analysis, visualization, ML pipelines, reporting.                   |
| `system-admin`      | `gpt-oss:120b`  | System administration, DevOps, infrastructure, technical ops.            |


### Codex Agentic Routing

The `agentic_routing_codex` plugin serves requests emitted by the **Codex CLI** coding agent. The CLI is pointed at a single
stable model name — the trigger `auto_codex` (declared in the models config as a `builtin` provider alias) — and the plugin rewrites
`payload["model"]` per request to the model that fits the work the agent is doing *right now*: planning, implementation, test runs,
git review, code review, debugging, one‑line thread titles (`aux_title`) or context compaction. The decision cascade is deterministic
first (request class, the `<collaboration_mode>` block the CLI injects, keyword scoring) with an optional embedding‑similarity layer
over the mode descriptions and examples. The plugin never rejects a request and is fail‑open on bad payloads; an inconsistent config
fails startup instead.

It is activated like any other utils plugin:

```bash
export LLM_ROUTER_UTILS_PLUGINS_PIPELINE="agentic_routing_codex"
```

Every model referenced by a mode (`codex_modes[].model_name`) must exist in `LLM_ROUTER_MODELS_CONFIG` as an active model with a
reachable provider, and its provider must support tool calling — Codex cannot operate without it.

**Shared session memory (optional, Redis‑backed).** Codex asks for one action per model call; between two calls the user's command
does not change, but the evidence does. The optional session memory carries the last *reliable* work phase of the current command
generation between successive requests of the same session (session + thread + agent), so a neutral request in the middle of an
action does not fall through to the fallback. It is **off by default** (`LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_MEMORY_ENABLED`),
shared between Gunicorn workers through a Redis instance of its own (its `…_REDIS_*` variables — the generic `LLM_ROUTER_REDIS_*`
and `LLM_ROUTER_AUTH_REDIS_*` variables are never used), stores no model names, conversation text, tool output or credentials, and is
consulted only when the deterministic layers stayed silent. A memory error (Redis outage, expired or damaged record) is a *miss*,
never a failed request — routing continues stateless; when memory is enabled, the connection is verified with `PING` at startup and
a failed check logs a warning and keeps routing stateless.

All `LLM_ROUTER_ROUTING_SEMANTIC_AGENTIC_CODEX_*` variables (config overrides, heuristic and embedding knobs, the `MEMORY_*` policy
and the `REDIS_*` connection settings) are documented in
[**ENV_DEFINITIONS.md → Codex Agentic Routing variables**](llm_router_api/docs/ENV_DEFINITIONS.md#codex-agentic-routing-variables),
and the plugin's own documentation (decision cascade, work modes, tuning, troubleshooting) lives in the `llm-router-plugins`
repository: [`llm_router_plugins/utils/routing/agentic_routing/codex/README.md`](
https://github.com/radlab-dev-group/llm-router-plugins/blob/main/llm_router_plugins/utils/routing/agentic_routing/codex/README.md
).

---

## 📦 Quick Start

### 1️⃣ Create & activate a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 2️⃣ Install (recommended: from PyPI)

The package is published on PyPI: [radlab-llm-router](https://pypi.org/project/radlab-llm-router/).

```shell
# Only the core library (llm-router-lib).
pip install radlab-llm-router

# Core library + API wrapper (llm-router-api).
pip install radlab-llm-router[api]

# Core library + API wrapper + Prometheus metrics.
pip install radlab-llm-router[api,metrics]
```

#### Or install from source (GitHub)

```shell
# Only the core library (llm-router-lib).
pip install .

# Core library + API wrapper (llm-router-api).
pip install .[api]

# Core library + API wrapper + Prometheus metrics.
pip install .[api,metrics]
```

> **Full installation guide (PIP / GitHub / Quay):**
> **[INSTALLATION.md](llm_router_api/docs/INSTALLATION.md)**

> **Note:** When Prometheus metrics are enabled, `LLM_ROUTER_USE_PROMETHEUS=1`
> must be set and **Redis is required** (used for provider availability state).  
> The multiproc directory defaults to
> `$HOME/.llm-router/metrics/prometheus/multiproc`
> — override via the `PROMETHEUS_MULTIPROC_DIR` environment variable if needed.

Then start the application with the environment variable set:

```bash
export LLM_ROUTER_USE_PROMETHEUS=1
```

When `LLM_ROUTER_USE_PROMETHEUS` is enabled, the router automatically registers a **`/metrics`** endpoint. It is served
at the literal `/metrics` — registered straight on the Flask app, so it is **not** prefixed with `LLM_ROUTER_EP_PREFIX`
and `/api/metrics` answers 404. Point the scrape config and the bundled Grafana dashboard at `/metrics`. The endpoint
exposes Prometheus‑compatible metrics such as request counts, latencies, and any custom counters defined by the
application.

#### 📊 Grafana dashboard example

A pre-built Grafana dashboard is available in
[
`resources/configs/prometheus/grafana-llm-router-dashboard-v1.json`](resources/configs/prometheus/grafana-llm-router-dashboard-v1.json).

Import steps:

1. Open your Grafana instance → **Dashboards** → **New** → **Import**.
2. Upload the `grafana-llm-router-dashboard-v1.json` file (or paste its contents).
3. Select the Prometheus data source that points to your LLM Router `/metrics` endpoint.
4. Click **Import** — the dashboard will display request counts, latencies, error rates, and provider usage at a glance.

### 3️⃣ Run the REST API

```shell
./run-rest-api.sh
# or
LLM_ROUTER_MINIMUM=1 python3 -m llm_router_api.rest_api
```

### 4️⃣ Quick‑start guides for local models

- **Gemma 3 12B‑IT** – [README](examples/quickstart/google-gemma3-12b-it/README.md)
- **Bielik 11B‑v2.3‑Instruct** – [README](examples/quickstart/speakleash-bielik-11b-v2_3-Instruct/README.md)

### 5️⃣ Integration boilerplates

Integration examples for popular LLM libraries (LlamaIndex, LangChain, OpenAI, LiteLLM, Haystack) are in the [
`examples/`](examples/) directory. See [examples README](examples/README.md) for details.

---

## 🔐 Auditing

The router can record request‑level events (guard‑rail checks, payload masking, custom logs) in a tamper‑evident,
encrypted form. All audit entries are written by the **auditor** module and stored under `logs/auditor/` as
GPG‑encrypted files.

For a complete guide — including key generation, encryption workflow, and decryption utilities — see:

➡️ **[Auditing subsystem documentation](llm_router_api/core/auditor/README.md)**

Utility scripts:

- `scripts/gen_and_export_gpg.sh` — generate and export GPG keys
- `scripts/decrypt_auditor_logs.sh` — decrypt encrypted audit logs

---

## 🔐 Authentication

The router supports API-key-based authentication with per-endpoint policies, rate limiting, and audit trail.

➡️ **[Authentication documentation](llm_router_api/docs/AUTHENTICATION.md)**

---

## ⏱️ Rate Limiting

Sliding-window rate limiting backed by Redis sorted sets. Each API key + IP gets a configurable number of requests per
minute. Returns `Retry-After` on 429 responses and exposes Prometheus metrics.

➡️ **[Rate Limiting documentation](llm_router_api/docs/RATE_LIMITING.md)**

---

## 🖥️ CLI Reference

The `llm-router` package provides a command-line tool for managing API keys, policies, rate-limit presets, and
anonymizing text. A full command reference is available here:

➡️ **[CLI Command Reference](llm_router_cli/README.md)**

---

## 🔒 Security

### 🔍 Error message sanitization

All error messages returned to API callers are sanitized to prevent leakage of internal infrastructure details (IP
addresses, hostnames, URLs, ports, connection strings).

**How it works:**

- `sanitize_error_message()` in [`llm_router_api/core/errors.py`](llm_router_api/core/errors.py) strips URLs, IP
  addresses, ports, hostnames, and urllib3/requests exception internals from error strings.
- Applied at every output choke point:
    - HTTP provider errors (`httprequest.py`)
    - Streaming error chunks (`stream_handler.py`)
    - `return_response_not_ok()` — the central error builder for all non-streaming errors
    - Parameter validation errors in `register.py`
- Server-side logs **still receive the full, unsanitized** exception — debugging remains fully possible.

**What you will see as a caller:**

- ✅ `"ConnectTimeout: The read operation timed out"`
- ✅ `"A connection error occurred"`

**What you will NOT see:**

- ❌ `192.168.x.x`, `10.0.x.x` — internal IPs
- ❌ `http://...`, `https://...` — internal URLs
- ❌ `port=8080`, `host='...'` — connection details
- ❌ Stack traces or internal provider addresses

This protection applies to all error responses regardless of whether they originate from HTTP provider calls, streaming
endpoints, or request validation.

---

## 📦 Docker

Run the container with the default configuration:

```bash
docker run -p 5555:8080 quay.io/radlab/llm-router:rc1
```

For more advanced usage you can use a custom launch script:

```shell
#!/bin/bash

PWD=$(pwd)

docker run \
  -p 5555:8080 \
  -e LLM_ROUTER_TIMEOUT=500 \
  -e LLM_ROUTER_IN_DEBUG=1 \
  -e LLM_ROUTER_VERBOSE=0 \
  -e LLM_ROUTER_MINIMUM=1 \
  -e LLM_ROUTER_EP_PREFIX="/api" \
  -e LLM_ROUTER_SERVER_TYPE=gunicorn \
  -e LLM_ROUTER_SERVER_PORT=8080 \
  -e LLM_ROUTER_SERVER_WORKERS_COUNT=4 \
  -e LLM_ROUTER_DEFAULT_EP_LANGUAGE="pl" \
  -e LLM_ROUTER_LOG_FILENAME="llm-proxy-rest.log" \
  -e LLM_ROUTER_EXTERNAL_TIMEOUT=300 \
  -e LLM_ROUTER_BALANCE_STRATEGY=balanced \
  -e LLM_ROUTER_REDIS_HOST="192.168.100.67" \
  -e LLM_ROUTER_REDIS_PORT=6379 \
  -e LLM_ROUTER_MODELS_CONFIG=/srv/cfg.json \
  -e LLM_ROUTER_PROMPTS_DIR="/srv/prompts" \
  -v "${PWD}/resources/configs/models-config.json":/srv/cfg.json \
  -v "${PWD}/resources/prompts":/srv/prompts \
  quay.io/radlab/llm-router:rc1
```

### Kubernetes (Helm)

Helm charts for Kubernetes deployment are available in the `helm_charts/` directory.

---

## Configuration

All environment variables are documented in **[ENV_DEFINITIONS.md](llm_router_api/docs/ENV_DEFINITIONS.md)**.

| Category                                                                          | Description                                                |
|-----------------------------------------------------------------------------------|------------------------------------------------------------|
| [Core, Redis](llm_router_api/README.md#core-variables)                            | Prompts, models config, timeouts, logging, server settings |
| [Masking & Guardrail](llm_router_api/README.md#masking--guardrail)                | Payload masking and content guardrails                     |
| [Semantic BiEncoder Routing](llm_router_api/README.md#semantic-biencoder-routing) | Semantic routing configuration                             |
| [Codex Agentic Routing](llm_router_api/README.md#codex-agentic-routing-variables) | Codex CLI routing plugin and its session-memory Redis configuration |
| [LangChainRAG](llm_router_api/README.md#langchainrag)                             | RAG plugin settings                                        |
| [Utils Plugins](llm_router_api/README.md#utils-plugins-variables)                 | Pipeline plugins configuration                             |
| [Authentication](llm_router_api/README.md#authentication)                         | Auth, key management, rate limiting                        |

> See full authentication docs: **[AUTHENTICATION.md](llm_router_api/docs/AUTHENTICATION.md)**

---

## ⚖️ Load Balancing Strategies

The current list of available strategies, the interface description, and an example extension can be found
at: [Load‑Balancing Strategies](llm_router_api/docs/LB_STRATEGIES.md#load-balancing-strategies)

Strategies: **balanced**, **weighted**, **dynamic_weighted**, **first_available**, **first_available_optim**, **first_available_optim_nworkers**.

---

## 🛣️ Endpoints Overview

The list of endpoints — categorized into built‑in, provider‑dependent, and utility endpoints — and a description of the
streaming mechanisms can be found at: [Endpoints Overview](llm_router_api/endpoints/README.md#endpoints-overview)

To create a custom endpoint, see the **[Endpoint Development Guide](llm_router_api/docs/ENDPOINT_DEV.md)** —
class hierarchy, `run_ep` lifecycle, payload hooks, guardrail/masking controls, and a worked example.

### Highlights

| Endpoint                                | Method | Auth (when `LLM_ROUTER_AUTH_ENABLED=true`) | Description                                                       |
|-----------------------------------------|--------|--------------------------------------------|-------------------------------------------------------------------|
| `/api/ping`                             | GET    | ❌ Requires `builtin` permission           | Health‑check (registered under `LLM_ROUTER_EP_PREFIX`)            |
| `/api/version`                          | GET    | ❌ Requires `builtin` permission           | Return router version (used by the SDK)                             |
| `/`                                     | GET    | ❌ Requires `chat` permission              | Ollama health endpoint                                             |
| `/models`                               | GET    | ❌ Requires `chat` permission              | List OpenAI‑compatible models                                     |
| `/health`                               | GET    | ✅ Public                                  | Router health check (no token)                                      |
| `/v1/models`                            | GET    | ❌ Requires `chat` permission              | List OpenAI‑compatible models (v1)                                |
| `/api/tags`                             | GET    | ❌ Requires `chat` permission              | List Ollama model tags                                            |
| `/api/v0/models`                        | GET    | ❌ Requires `chat` permission              | List LM Studio models                                             |
| `/metrics`                              | GET    | ✅ Public                                  | Prometheus metrics (requires `LLM_ROUTER_USE_PROMETHEUS=1`)       |
| `/chat/completions`                     | POST   | ❌ Requires `chat` permission              | OpenAI‑style chat completion                                      |
| `/api/chat/completions`                 | POST   | ❌ Requires `chat` permission              | OpenAI‑style chat completion (with prefix)                        |
| `/v1/chat/completions`                  | POST   | ❌ Requires `chat` permission              | vLLM‑like chat completion                                         |
| `/v1/messages`                          | POST   | ❌ Requires `anthropic` permission         | Anthropic‑compatible messages endpoint (Claude)                   |
| `/responses`                            | POST   | ❌ Requires `chat` permission              | OpenAI‑like responses endpoint                                    |
| `/v1/responses`                         | POST   | ❌ Requires `chat` permission              | OpenAI‑like responses endpoint (v1)                               |
| `/embeddings`                           | POST   | ❌ Requires `embedding` permission         | Standard embeddings                                               |
| `/api/embeddings`                       | POST   | ❌ Requires `embedding` permission         | Standard embeddings (with prefix)                                 |
| `/v1/embeddings`                        | POST   | ❌ Requires `embedding` permission         | OpenAI‑compatible embeddings endpoint                             |
| `/api/embed`                            | POST   | ❌ Requires `embedding` permission         | Ollama‑native embeddings endpoint                                 |
| `/api/chat`                             | POST   | ❌ Requires `ollama` permission            | Ollama‑style chat completion                                      |
| `/api/conversation_with_model`          | POST   | ❌ Requires `builtin` permission           | Built‑in standard chat                                            |
| `/api/extended_conversation_with_model` | POST   | ❌ Requires `builtin` permission           | Built‑in chat with extended fields                                |
| `/api/generative_answer`                | POST   | ❌ Requires `builtin` permission           | Answer a question using provided context                          |
| `/api/polarity_3c`                      | POST   | ❌ Requires `builtin` permission           | Detect 3-class polarity for input texts                           |
| `/api/translate`                        | POST   | ❌ Requires `builtin` permission           | Translate texts                                                   |
| `/api/generate_questions`               | POST   | ❌ Requires `builtin` permission           | Generate questions from texts                                     |
| `/api/simplify_text`                    | POST   | ❌ Requires `builtin` permission           | Simplify input texts                                              |
| `/api/generate_label`                   | POST   | ❌ Requires `builtin` permission           | Generate a category name (label) from input texts                 |
| `/api/generate_article_from_texts`      | POST   | ❌ Requires `builtin` permission           | Generate a short (~A4) Polish article summarising a list of texts |
| `/api/create_full_article_from_texts`   | POST   | ❌ Requires `builtin` permission           | Create a fuller article framed by `user_query`                    |
| `/api/polarity_3c`                      | POST   | ❌ Requires `builtin` permission           | Detect 3-class polarity for input texts                           |
| `/api/translate`                        | POST   | ❌ Requires `builtin` permission           | Translate texts                                                   |
| `/api/generate_questions`               | POST   | ❌ Requires `builtin` permission           | Generate questions from texts                                     |
| `/api/simplify_text`                    | POST   | ❌ Requires `builtin` permission           | Simplify input texts                                              |

> **Note:** By default `LLM_ROUTER_AUTH_ENABLED=false`, so all endpoints are accessible without authentication. Set it
> to `"true"` to enforce auth. `LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS` defaults to **`/metrics,/health`** — those two are
> the only paths that bypass auth out of the box. Every `/models`, `/`, `/api/ping` and `/api/version` request needs a key
> (see the table above). Matching is done on the raw request path, so a bare entry never matches a prefixed route: to use
> `/api/ping` as a key-free probe, add that exact path, e.g.
> `LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS="/metrics,/health,/api/ping"`. For each entry `/v1<entry>` is matched too.

## 🌐 Web Applications

### Config Manager (port **8081**)

Full web UI for managing LLM Router model configurations:

- **Multi‑user** with authentication and role‑based access (admin/user)
- **Projects** — group configurations by project
- **Model configuration** — create, edit, import/export JSON configs; manage providers across families (Google, OpenAI,
  Qwen)
- **Version control** — snapshot history with restore capability
- **Active model selection** — choose which models to activate per config
- **Drag‑and‑drop** provider reordering (HTMX)
- **Light/dark themes** (Alpine.js)
- 26+ API endpoints under `/configs`

Run: `./run-configs-manager.sh`

### Anonymizer (port **8082**)

Web UI for text anonymization and interactive chat:

- **3 anonymization algorithms**: `fast` (regex), `pii_masking` (ML model), `fast+pii` (hybrid)
- **Interactive chat** with streaming SSE responses and session persistence
- **Dynamic model selection** from the router
- **i18n** — Polish and English translations (122 keys)
- **Privacy warnings** when anonymization is disabled
- **Privacy policy & terms** pages

Run: `./run-anonymizer.sh`

---

## 🧰 llm-router-utils

The `llm-router-utils` repository provides CLI tools and ready‑made deployment configs:

### CLI Tools

| Tool               | Description                                                                   |
|--------------------|-------------------------------------------------------------------------------|
| `translate-texts`  | Batch translate texts in JSON/JSONL datasets via LLM Router                   |
| `genai-classifier` | Classify dataset texts using LLM prompts with multi‑threading and XLSX export |

### Speakleash Deployment Configs

The `resources/llm-router-speakleash/` directory contains ready‑made configs for deploying Speakleash models:

- `speakleash-models.json` — configures `Bielik-11B-v2.3-Instruct` across **8 vLLM providers** on 3 hosts
- `run-bielik-*.sh` — vLLM launch scripts for each GPU (cuda:0, cuda:1, cuda:2)
- `run-rest-api-gunicorn.sh` — full LLM Router server with masking, guardrails, Redis balancing, and Prometheus metrics
- `run-sojka-guardrail.sh` — guardrail service with Bielik‑Guard model

---

## ⚙️ Configuration Details

| Config File / Variable                             | Meaning                                                                                               |
|----------------------------------------------------|-------------------------------------------------------------------------------------------------------|
| `resources/configs/models-config.json`             | JSON map of provider → model → default options (e.g., `keep_alive`, `options.num_ctx`).               |
| `LLM_ROUTER_PROMPTS_DIR`                           | Directory containing prompt templates (`*.prompt`). Sub‑folders are language‑specific (`en/`, `pl/`). |
| `LLM_ROUTER_DEFAULT_EP_LANGUAGE`                   | Language code used when a prompt does not explicitly specify one.                                     |
| `LLM_ROUTER_TIMEOUT`                               | Upper bound for any request to an upstream LLM (seconds).                                             |
| `LLM_ROUTER_LOG_FILENAME` / `LLM_ROUTER_LOG_LEVEL` | Logging destinations and verbosity.                                                                   |
| `LLM_ROUTER_IN_DEBUG`                              | When set, enables DEBUG‑level logs and more verbose error payloads.                                   |
| `LLM_ROUTER_VERBOSE`                               | When set, endpoints log raw, **unmasked** request params (PII); startup warns, then pauses 3 s.       |

---

## 🔧 Development

- **Python** 3.10+ (project is tested on 3.10.6)
- All dependencies are listed in `requirements.txt`. Install them inside the virtualenv.
- To add a new provider, create a class in `llm_router_api/core/api_types` that implements the `BaseProvider` interface
  and register it in `llm_router_api/register/__init__.py`.

---

## 📚 Changelog

See the [CHANGELOG](CHANGELOG.md) for a complete history of changes.

## 📜 License

See the [LICENSE](LICENSE) file.
