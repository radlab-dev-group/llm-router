# LLM Router - Open-Source AI Gateway for Local and Cloud LLM Infrastructure

**Version: 0.5.1**

[**LLM Router**](https://llm-router.cloud) is a service that can be deployed on‑premises or in the cloud. It adds a
layer between any application and the LLM provider. In real time it controls traffic, distributes load among providers
of a specific LLM, and enables analysis of outgoing requests from a security perspective (masking, anonymization,
prohibited content). It is an open‑source solution (Apache 2.0) that can be launched instantly by running a ready‑made
image in your own infrastructure.

---

## 🌐 Ecosystem Overview

The LLM‑Router project is split across five dedicated repositories:

| Repository                                                                         | Description                                                                                                                                                                                                            |
|------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **[llm-router](https://github.com/radlab-dev-group/llm-router)** (this repo)       | Core gateway — unified REST proxy, Python SDK, and configuration management                                                                                                                                            |
| **[llm-router-api](https://github.com/radlab-dev-group/llm-router)**               | REST proxy that routes requests to any supported LLM backend (OpenAI‑compatible, Ollama, vLLM, LM Studio, Anthropic), with built‑in load‑balancing, health checks, streaming responses and optional Prometheus metrics |
| **[llm-router-lib](https://github.com/radlab-dev-group/llm-router)**               | Python SDK that wraps the API with typed request/response models, automatic retries, token handling and a rich exception hierarchy                                                                                     |
| **[llm-router-web](https://github.com/radlab-dev-group/llm-router-web)**           | Ready‑to‑use Flask UIs — a Config Manager for model/user settings and an Anonymizer UI that masks sensitive data                                                                                                       |
| **[llm-router-plugins](https://github.com/radlab-dev-group/llm-router-plugins)**   | Pluggable anonymizers (maskers), guardrails, semantic routing and RAG plugins                                                                                                                                          |
| **[llm-router-services](https://github.com/radlab-dev-group/llm-router-services)** | HTTP services that power the plugin ecosystem (NASK‑PIB/Sojka guardrails, PII masker)                                                                                                                                  |
| **[llm-router-utils](https://github.com/radlab-dev-group/llm-router-utils)**       | CLI tools, batch translation, GenAI classification and ready‑made deployment configs (Speakleash models)                                                                                                               |

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
| **Health & metadata endpoints**     | `/ping` (simple 200 OK) and `/tags` (available model tags/metadata).                                                                                                                                                                        |
| **Embeddings support**              | Dedicated endpoints for generating text embeddings across all supported providers.                                                                                                                                                          |
| **Simple deployment**               | One‑liner run script, Docker image, or Helm chart for Kubernetes.                                                                                                                                                                           |
| **Extensible conversation formats** | Basic chat, conversation with system prompt, and extended conversation with richer options (temperature, top‑k, custom system prompt).                                                                                                      |
| **Multi‑provider model support**    | Each model can be backed by multiple providers (VLLM, Ollama, OpenAI, Anthropic) defined in `models-config.json`.                                                                                                                           |
| **Load‑balanced default strategy**  | `LoadBalancedStrategy` distributes requests evenly across providers using in‑memory usage counters.                                                                                                                                         |
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

| Plugin ID                     | Type  | Description                                                                                                                        |
|-------------------------------|-------|------------------------------------------------------------------------------------------------------------------------------------|
| **`langchain_rag`**           | Local | Retrieves relevant document chunks from a FAISS vector store and injects them into the payload for Retrieval‑Augmented Generation. |
| **`simple_semantic_routing`** | Local | Two‑stage heuristic model selection: intent classification + complexity analysis. Activated when `payload["model"] == "auto"`.     |

### Configuration

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

---

## 🛡️ Monitoring

| Component            | Description                                                                         |
|----------------------|-------------------------------------------------------------------------------------|
| **KeepAliveMonitor** | Periodically pings model endpoints to keep them warm (prevents cold‑start latency). |
| **ProviderMonitor**  | Tracks per‑provider availability using Redis as a shared state store.               |
| **ServicesMonitor**  | Periodically health‑checks the llm-router-services endpoints (guardrails, maskers). |

---

## 📦 Quick Start

### 1️⃣ Create & activate a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate

# Only the core library (llm-router-lib).
pip install .

# Core library + API wrapper (llm-router-api).
pip install .[api]

# Core library + API wrapper + Prometheus metrics.
pip install .[api,metrics]
```

> **Note:** When Prometheus metrics are enabled, `LLM_ROUTER_USE_PROMETHEUS=1` must be set and **Redis is required** (
> used for provider availability state).

Then start the application with the environment variable set:

```bash
export LLM_ROUTER_USE_PROMETHEUS=1
```

When `LLM_ROUTER_USE_PROMETHEUS` is enabled, the router automatically registers a **`/metrics`** endpoint (under the API
prefix, e.g. `/api/metrics`). This endpoint exposes Prometheus‑compatible metrics such as request counts, latencies, and
any custom counters defined by the application.

### 2️⃣ Run the REST API

```shell
./run-rest-api.sh
# or
LLM_ROUTER_MINIMUM=1 python3 -m llm_router_api.rest_api
```

### 3️⃣ Quick‑start guides for local models

- **Gemma 3 12B‑IT** – [README](examples/quickstart/google-gemma3-12b-it/README.md)
- **Bielik 11B‑v2.3‑Instruct** – [README](examples/quickstart/speakleash-bielik-11b-v2_3-Instruct/README.md)

### 4️⃣ Integration boilerplates

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

This protection applies to all error responses regardless of whether they originate from HTTP provider calls, 
streaming endpoints, or request validation.

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

## 🛠️ Configuration (via environment)

A full list of environment variables is available at: [API README](llm_router_api/README.md#environment-variables)

### Core variables

| Variable                           | Default                                | Description                                                                                                          |
|------------------------------------|----------------------------------------|----------------------------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_PROMPTS_DIR`           | `resources/prompts`                    | Directory containing predefined system prompts.                                                                      |
| `LLM_ROUTER_MODELS_CONFIG`         | `resources/configs/models-config.json` | Path to the models configuration JSON file.                                                                          |
| `LLM_ROUTER_DEFAULT_EP_LANGUAGE`   | `pl`                                   | Default language for endpoint prompts.                                                                               |
| `LLM_ROUTER_TIMEOUT`               | `0`                                    | Timeout (seconds) for llm-router API calls.                                                                          |
| `LLM_ROUTER_EXTERNAL_TIMEOUT`      | `300`                                  | Timeout (seconds) for external model API calls.                                                                      |
| `LLM_ROUTER_MAX_REQUEST_BODY_SIZE` | `10485760` (10 MB)                     | Maximum allowed request body size in bytes. Larger payloads are rejected with HTTP 413 to prevent memory exhaustion. |
| `LLM_ROUTER_LOG_FILENAME`          | `llm-router.log`                       | Name of the log file.                                                                                                |
| `LLM_ROUTER_LOG_LEVEL`             | `INFO`                                 | Logging level (e.g., INFO, DEBUG).                                                                                   |
| `LLM_ROUTER_EP_PREFIX`             | `/api`                                 | Prefix for all API endpoints.                                                                                        |
| `LLM_ROUTER_MINIMUM`               | `False`                                | Run service in proxy‑only mode.                                                                                      |
| `LLM_ROUTER_IN_DEBUG`              | `False`                                | Run server in debug mode.                                                                                            |
| `LLM_ROUTER_BALANCE_STRATEGY`      | `balanced`                             | Load‑balancing strategy: `balanced`, `weighted`, `dynamic_weighted`, `first_available`, `first_available_optim`.     |
| `LLM_ROUTER_SERVER_TYPE`           | `flask`                                | Server implementation: `flask`, `gunicorn`, `waitress`.                                                              |
| `LLM_ROUTER_SERVER_PORT`           | `8080`                                 | Port on which the server listens.                                                                                    |
| `LLM_ROUTER_SERVER_HOST`           | `localhost`                            | Host address for the server.                                                                                         |
| `LLM_ROUTER_SERVER_WORKERS_COUNT`  | `2`                                    | Number of workers.                                                                                                   |
| `LLM_ROUTER_SERVER_THREADS_COUNT`  | `8`                                    | Number of worker threads.                                                                                            |
| `LLM_ROUTER_SERVER_WORKER_CLASS`   | `None`                                 | Worker class for servers that support it.                                                                            |
| `LLM_ROUTER_USE_PROMETHEUS`        | `False`                                | Enable Prometheus metrics (`/metrics` endpoint).                                                                     |

### Masking & guardrail variables

| Variable                                | Default           | Description                                                     |
|-----------------------------------------|-------------------|-----------------------------------------------------------------|
| `LLM_ROUTER_FORCE_MASKING`              | `False`           | Enable force‑masking of every endpoint's payload.               |
| `LLM_ROUTER_MASKING_STRATEGY_PIPELINE`  | `["fast_masker"]` | Ordered list of masker plugins (e.g. `fast_masker,pii_masker`). |
| `LLM_ROUTER_MASKING_WITH_AUDIT`         | `False`           | Record each masking operation in the audit log.                 |
| `LLM_ROUTER_FORCE_GUARDRAIL_REQUEST`    | `False`           | Force guardrail evaluation on every request.                    |
| `LLM_ROUTER_MASKER_PII_HOST`            | —                 | Host URL for the PII masker service.                            |
| `LLM_ROUTER_GUARDRAIL_SOJKA_GUARD_HOST` | —                 | Host URL for the Sojka guardrail service.                       |

### Redis variables

| Variable                    | Default     | Description                                                 |
|-----------------------------|-------------|-------------------------------------------------------------|
| `LLM_ROUTER_REDIS_HOST`     | *(empty)*   | Redis host for load‑balancing across multi‑provider models. |
| `LLM_ROUTER_REDIS_PORT`     | `6379`      | Redis port.                                                 |
| `LLM_ROUTER_REDIS_PASSWORD` | *(not set)* | Redis password.                                             |
| `LLM_ROUTER_REDIS_DB`       | `0`         | Redis database number.                                      |

> **Redis is now mandatory.** The router raises `RuntimeError` at startup if Redis is unavailable.

---

## ⚖️ Load Balancing Strategies

The current list of available strategies, the interface description, and an example extension can be found
at: [Load‑Balancing Strategies](llm_router_api/LB_STRATEGIES.md#load-balancing-strategies)

Strategies: **balanced**, **weighted**, **dynamic_weighted**, **first_available**, **first_available_optim**.

---

## 🛣️ Endpoints Overview

The list of endpoints — categorized into built‑in, provider‑dependent, and utility endpoints — and a description of the
streaming mechanisms can be found at: [Endpoints Overview](llm_router_api/endpoints/README.md#endpoints-overview)

### Highlights

| Endpoint                                | Method | Description                                     |
|-----------------------------------------|--------|-------------------------------------------------|
| `/ping`                                 | GET    | Health‑check                                    |
| `/tags`                                 | GET    | List Ollama model tags                          |
| `/models`                               | GET    | List OpenAI‑compatible models                   |
| `/api/chat/completions`                 | POST   | OpenAI‑style chat completion                    |
| `/api/v1/chat/completions`              | POST   | vLLM‑like chat completion                       |
| `/v1/messages`                          | POST   | Anthropic‑compatible messages endpoint (Claude) |
| `/v1/responses`                         | POST   | OpenAI‑like responses endpoint                  |
| `/api/embeddings`                       | POST   | Standard embeddings                             |
| `/api/conversation_with_model`          | POST   | Built‑in standard chat                          |
| `/api/extended_conversation_with_model` | POST   | Built‑in chat with extended fields              |
| `/api/generative_answer`                | POST   | Answer a question using provided context        |
| `/api/translate`                        | POST   | Translate texts                                 |
| `/api/generate_questions`               | POST   | Generate questions from texts                   |
| `/api/simplify_text`                    | POST   | Simplify input texts                            |

---

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
