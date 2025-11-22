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

| Variable                                    | Description                                                                                                                                                                                                                                                              | Default                                |
|---------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------|
| `LLM_ROUTER_PROMPTS_DIR`                    | Directory containing predefined system prompts.                                                                                                                                                                                                                          | `resources/prompts`                    |
| `LLM_ROUTER_MODELS_CONFIG`                  | Path to the models configuration JSON file.                                                                                                                                                                                                                              | `resources/configs/models-config.json` |
| `LLM_ROUTER_DEFAULT_EP_LANGUAGE`            | Default language for endpoint prompts.                                                                                                                                                                                                                                   | `pl`                                   |
| `LLM_ROUTER_TIMEOUT`                        | Timeout (seconds) for llm-router API calls.                                                                                                                                                                                                                              | `0`                                    |
| `LLM_ROUTER_EXTERNAL_TIMEOUT`               | Timeout (seconds) for external model API calls.                                                                                                                                                                                                                          | `300`                                  |
| `LLM_ROUTER_LOG_FILENAME`                   | Name of the log file.                                                                                                                                                                                                                                                    | `llm-router.log`                       |
| `LLM_ROUTER_LOG_LEVEL`                      | Logging level (e.g., INFO, DEBUG).                                                                                                                                                                                                                                       | `INFO`                                 |
| `LLM_ROUTER_EP_PREFIX`                      | Prefix for all API endpoints.                                                                                                                                                                                                                                            | `/api`                                 |
| `LLM_ROUTER_MINIMUM`                        | Run service in proxy‑only mode (boolean).                                                                                                                                                                                                                                | `False`                                |
| `LLM_ROUTER_IN_DEBUG`                       | Run server in debug mode (boolean).                                                                                                                                                                                                                                      | `False`                                |
| `LLM_ROUTER_BALANCE_STRATEGY`               | Strategy used to balance routing between LLM providers. Allowed values are `balanced`, `weighted`, `dynamic_weighted` (beta), `first_available` and `first_available_optim` as defined in `constants_base.py`.                                                           | `balanced`                             |
| `LLM_ROUTER_REDIS_HOST`                     | Redis host for load‑balancing when a multi‑provider model is available.                                                                                                                                                                                                  | `<empty string>`                       |
| `LLM_ROUTER_REDIS_PORT`                     | Redis port for load‑balancing when a multi‑provider model is available.                                                                                                                                                                                                  | `6379`                                 |
| `LLM_ROUTER_SERVER_TYPE`                    | Server implementation to use (`flask`, `gunicorn`, `waitress`).                                                                                                                                                                                                          | `flask`                                |
| `LLM_ROUTER_SERVER_PORT`                    | Port on which the server listens.                                                                                                                                                                                                                                        | `8080`                                 |
| `LLM_ROUTER_SERVER_HOST`                    | Host address for the server.                                                                                                                                                                                                                                             | `0.0.0.0`                              |
| `LLM_ROUTER_SERVER_WORKERS_COUNT`           | Number of workers (used in case when the selected server type supports multiworkers)                                                                                                                                                                                     | `2`                                    |
| `LLM_ROUTER_SERVER_THREADS_COUNT`           | Number of workers threads (used in case when the selected server type supports multithreading)                                                                                                                                                                           | `8`                                    |
| `LLM_ROUTER_SERVER_WORKER_CLASS`            | If server accepts workers type, its able to set worker class by this environment.                                                                                                                                                                                        | `None`                                 |
| `LLM_ROUTER_USE_PROMETHEUS`                 | Enable Prometheus metrics collection.** When set to `True`, the router registers a `/metrics` endpoint exposing Prometheus‑compatible metrics for monitoring.                                                                                                            | `False`                                |
| `LLM_ROUTER_FORCE_MASKING`                  | Enable force-masking payload of each endpoint. Each key and value is masked before sending to model provider.                                                                                                                                                            | `False`                                |
| `LLM_ROUTER_MASKING_WITH_AUDIT`             | When enabled, each masking operation is recorded in an audit log. This helps with compliance and traceability by providing a tamper‑evident record of what data was masked and when.                                                                                     | `False`                                |
| `LLM_ROUTER_MASKING_STRATEGY_PIPELINE`      | Defines the ordered list of masking strategies that will be applied to the request payload. For example, ['fast_masker', 'my_new_masker_strategy'] runs the fast masker first, then the `my_new_masker_strategy` masker. This allows flexible, composable masking flows. | `['fast_masker']`                      |
| `LLM_ROUTER_ENABLE_GENAI_ANONYMIZE_TEXT_EP` | Enable builtin endpoint `/api/anonymize_text_genai` which uses genai to anonymize text                                                                                                                                                                                   | `False`                                |
| `LLM_ROUTER_FORCE_GUARDRAIL_REQUEST`        | Forces guardrail evaluation on every request.                                                                                                                                                                                                                            | `False`                                |
| `LLM_ROUTER_GUARDRAIL_WITH_AUDIT_REQUEST`   | Audits all guardrail decisions.                                                                                                                                                                                                                                          | `False`                                |
| `GUARDRAIL_STRATEGY_PIPELINE_REQUEST`       | Ordered list of guardrail strategies.                                                                                                                                                                                                                                    | `-`                                    |
| `LLM_ROUTER_FORCE_GUARDRAIL_RESPONSE`       | Forces guardrail evaluation on every response before user recieve the result.                                                                                                                                                                                            | `False`                                |
| `LLM_ROUTER_GUARDRAIL_WITH_AUDIT_RESPONSE`  | Audits all guardrail decisions (response).                                                                                                                                                                                                                               | `False`                                |
| `GUARDRAIL_STRATEGY_PIPELINE_RESPONSE`      | Ordered list of guardrail strategies (response).                                                                                                                                                                                                                         | `-`                                    |

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

| Method | Path                                     | Description                                                   |
|--------|------------------------------------------|---------------------------------------------------------------|
| `GET`  | `/api/ping`                              | Health‑check, returns `"pong"`                                |
| `GET`  | `/`                                      | Ollama health endpoint (`"Ollama is running"`).               |
| `GET`  | `/tags`                                  | List available Ollama model tags.                             |
| `GET`  | `/models`                                | List OpenAI‑compatible model tags.                            |
| `POST` | `/api/conversation_with_model`           | Chat endpoint (builtin).                                      |
| `POST` | `/api/extended_conversation_with_model`  | Chat with extra fields (builtin).                             |
| `POST` | `/api/generate_questions`                | Generate questions from texts (builtin).                      |
| `POST` | `/api/translate`                         | Translate a list of texts (builtin).                          |
| `POST` | `/api/simplify_text`                     | Simplify texts (builtin).                                     |
| `POST` | `/api/generate_article_from_text`        | Generate article from a single text (builtin).                |
| `POST` | `/api/create_full_article_from_texts`    | Generate a full article from multiple texts (builtin).        |
| `POST` | `/api/generative_answer`                 | Answer a question using a context (builtin).                  |
| `POST` | `/api/v0/models`                         | List LM Studio models.                                        |
| `POST` | `/api/chat` (or provider‑specific paths) | Proxy to the underlying provider’s chat/completions endpoint. |

**Payload format** follows the OpenAI schema (`model`, `messages`, optional `stream`, etc.) unless a custom endpoint
overrides it.

All endpoints automatically:

- Validate required arguments (via `REQUIRED_ARGS`).
- Resolve the appropriate provider using the configured **load‑balancing strategy**.
- Inject system prompts when `SYSTEM_PROMPT_NAME` is defined.
- Return a JSON response with `{ "status": true, "body": … }` or an error payload.

Streaming responses are returned as **Server‑Sent Events (SSE)** (`text/event-stream`) and are compatible with both
OpenAI‑style and Ollama‑style streams.

---

## Load‑Balancing Strategies

The router selects a provider for a given model request using the **ProviderChooser**. The strategy can be chosen via
the `LLM_ROUTER_BALANCE_STRATEGY` variable.

| Strategy             | Description                                                                                   |
|----------------------|-----------------------------------------------------------------------------------------------|
| **balanced**         | Simple round‑robin based on usage counters.                                                   |
| **weighted**         | Static weights defined in each provider configuration (`weight` field).                       |
| **dynamic_weighted** | Weights are updated at runtime; tracks latency and failure penalties.                         |
| **first_available**  | Uses Redis locks to guarantee exclusive access to a provider (useful for stateful back‑ends). |

Custom strategies can be added by subclassing `ChooseProviderStrategyI` and registering the class in
`llm_router_api.base.lb.chooser.STRATEGIES`.

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
- Tracks request counts, latency histograms, in‑progress gauges, and error counters.

You can scrape this endpoint with a Prometheus server or query it manually.

---

## License

`llm-router-api` is released under the **MIT License**. See the `LICENSE` file in the repository for full terms.  