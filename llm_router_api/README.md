# llm‑router‑api

**llm‑router‑api** is a lightweight Python library that provides a flexible, extensible proxy for Large Language Model (
LLM) back‑ends. It abstracts the details of multiple model providers (OpenAI‑compatible, Ollama, vLLM, LM Studio, etc.)
and offers a unified REST interface with built‑in load‑balancing, health‑checking, and monitoring.

> **Repository:** <https://github.com/radlab-dev-group/llm-router>

---

## Features

- **Unified API** – One REST surface (`/api/...`) that proxies calls to any supported LLM back‑end.
- **Provider Selection** – Choose a provider per request using pluggable strategies (balanced, weighted, adaptive,
  first‑available).
- **Prompt Management** – System prompts are stored as files and can be dynamically injected with placeholder
  substitution.
- **Streaming Support** – Transparent streaming for both OpenAI‑compatible and Ollama endpoints.
- **Health Checks** – Built‑in ping endpoint and Redis‑based provider health monitoring.
- **Prometheus Metrics** – Optional instrumentation for request counts, latencies, and error rates.
- **Auto‑Discovery** – Endpoints are automatically discovered and instantiated at startup.
- **Extensible** – Add new providers, strategies, or custom endpoints with minimal boilerplate.

---

## Installation

The project uses **Python 3.10.6** and a **virtualenv**‑based workflow.

```shell script
# Clone the repository
git clone https://github.com/radlab-dev-group/llm-router.git
cd llm-router

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install the package (including optional extras)
pip install -e .[metrics]   # installs Prometheus support
```

All required third‑party libraries are listed in `requirements.txt` (e.g., Flask, requests, redis, rdl‑ml‑utils, etc.).

---

## Configuration

Configuration is driven primarily by environment variables and a JSON model‑config file.

### Environment Variables

All environment variables are documented in **[ENV_DEFINITIONS.md](./ENV_DEFINITIONS.md)**.

Key categories: **Core** · **Redis** · **Masking & Guardrail** · **Semantic BiEncoder Routing** · **LangChainRAG** · *
*Utils Plugins** · **Authentication**.

---

### Authentication variables

Auth-specific environment variables are documented in **[ENV_DEFINITIONS.md](./ENV_DEFINITIONS.md) → Authentication
section**.

> See full authentication docs: **[AUTHENTICATION.md](AUTHENTICATION.md)**

### Model Configuration

`models-config.json` follows the schema:

```json
{
  "active_models": {
    "openai_models": [
      "gpt-4",
      "gpt-3.5-turbo"
    ],
    "ollama_models": [
      "llama2"
    ]
  },
  "openai_models": {
    "gpt-4": {
      "providers": [
        {
          "id": "openai-gpt4-1",
          "api_host": "https://api.openai.com/v1",
          "api_token": "sk-...",
          "api_type": "openai",
          "input_size": 8192,
          "model_path": ""
        }
      ]
    }
  },
  ...
}
```

Only the fields required by the router are needed: `id`, `api_host`, `api_token` (optional), `api_type`, `input_size`,
and optionally `model_path`.

**Configuration Details** – see the full schema and a ready‑made example in [MODELS_CONFIG.md](MODELS_CONFIG.md).

---

## Running the Server

The entry point is `llm_router_api.rest_api`. Choose a server backend via the `LLM_ROUTER_SERVER_TYPE` variable or
command‑line flags.

```shell script
# Using the built‑in Flask development server (default)
python -m llm_router_api.rest_api

# Production‑grade with Gunicorn (streaming supported)
python -m llm_router_api.rest_api --gunicorn

# Windows‑friendly Waitress server
python -m llm_router_api.rest_api --waitress
```

The server starts on the host/port defined by `LLM_ROUTER_SERVER_HOST` and `LLM_ROUTER_SERVER_PORT` (default
`0.0.0.0:8080`).

**Note:** The service must be launched with `LLM_ROUTER_MINIMUM=1` (or any truthy value) because it operates in
“proxy‑only” mode.

---

## REST API Overview

All routes are prefixed by `LLM_ROUTER_EP_PREFIX` (default `/api`).
The list of endpoints—categorized into built‑in, provider‑dependent, and extended endpoints—and
a description of the streaming mechanisms can be found at the link:
[load endpoints overview](endpoints/README.md#endpoints-overview)

---

## Load‑Balancing Strategies

The router selects a provider for a given model request using the **ProviderChooser**. The strategy can be chosen via
the `LLM_ROUTER_BALANCE_STRATEGY` variable.

The current list of available strategies, the interface description,
and an example extension can be found at the link
[load balancing strategies](LB_STRATEGIES.md#load-balancing-strategies)

---

## Keep‑Alive Mechanism

The keep‑alive subsystem periodically pings model endpoints to keep them warm, reducing latency for the first request
after idle periods. Configuration is driven by the `keep_alive` field in the provider definition
(see [KEEPALIVE.md](KEEPALIVE.md)). Strategies that select providers can register usage with the `KeepAliveMonitor`,
which handles scheduling and background execution.

For details on how to enable and configure keep‑alive, refer to the dedicated documentation:
[Keep‑Alive Overview](KEEPALIVE.md)

---

## Extending the Router

### Adding a New Provider Type

1. **Implement `ApiTypesI`**  
   Create a class (e.g., `MyProviderType`) that implements the abstract methods `chat_ep`, `chat_method`,
   `completions_ep`, and `completions_method`.
2. **Register in Dispatcher**  
   Add the class to `ApiTypesDispatcher._REGISTRY` with a lowercase key.
3. **Update Constants (optional)**  
   If you need a new balance strategy, extend `BalanceStrategies` in `constants_base.py`.

### Adding a New Endpoint

1. Choose a base class:
    - `EndpointWithHttpRequestI` for full proxy behaviour (default).
    - `PassthroughI` if you only need to forward the request unchanged.
    - Directly subclass `EndpointI` for non‑proxy use cases.
2. Define `REQUIRED_ARGS`, `OPTIONAL_ARGS`, and optionally `SYSTEM_PROMPT_NAME`.
3. Implement `prepare_payload(self, params)` – convert incoming parameters to the payload expected by the downstream
   model.
4. (Optional) Set `self._prepare_response_function` to post‑process the model response.
5. The endpoint will be auto‑discovered by `EndpointAutoLoader` at startup.

### Prompt Files

Prompt files live under the directory configured by `LLM_ROUTER_PROMPTS_DIR`.  
File naming convention: `<category>/system/<lang>/<prompt-id>`.  
Placeholders such as `##PLACEHOLDER##` can be replaced via `self._map_prompt` in the endpoint implementation.

---

## Monitoring & Metrics

When `LLM_ROUTER_USE_PROMETHEUS=1` (or `true`) the router automatically:

- Exposes a `/metrics` endpoint (Prometheus format).
- Tracks HTTP request counts, latency histograms, in‑progress gauges, and error counters.
- Tracks auth events, rate limits, and key budget usage.
- **Tracks provider-level metrics:** calls per provider type, provider latency/errors, load balancing strategy
  selection, pipeline funnel stages, retry attempts, token usage (input/output), streaming format distribution, and
  payload conversion counts.

See **[ROUTING_METRICS.md](./ROUTING_METRICS.md)** for the full list of 10 new router metrics with documentation,
example PromQL queries, and Grafana dashboard snippets.

You can scrape this endpoint with a Prometheus server or query it manually.

---

## License

`llm-router-api` is released under the **Apache 2.0**. See the `LICENSE` file in the repository for full terms.  