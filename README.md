## llm‑router

A lightweight, extensible gateway that exposes a clean **REST** API for interacting with
multiple Large Language Model (LLM) providers (OpenAI, Ollama, vLLM, etc.).  
It centralises request validation, prompt management, model configuration and logging,
allowing your application to talk to any supported LLM through a single, consistent interface.

---

### ✨ Key Features

| Feature                             | Description                                                                                                                                             |
|-------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Unified REST interface**          | One endpoint schema works for OpenAI‑compatible, Ollama, vLLM and any future provider.                                                                  |
| **Provider‑agnostic streaming**     | The `stream` flag (default `true`) controls whether the proxy forwards **chunked** responses as they arrive or returns a **single** aggregated payload. |
| **Built‑in prompt library**         | Language‑aware system prompts stored under `resources/prompts` can be referenced automatically.                                                         |
| **Dynamic model configuration**     | JSON file (`models-config.json`) defines providers, model name, default options and per‑model overrides.                                                |
| **Request validation**              | Pydantic models guarantee correct payloads; errors are returned with clear messages.                                                                    |
| **Structured logging**              | Configurable log level, filename, and optional JSON formatting.                                                                                         |
| **Health & metadata endpoints**     | `/ping` (simple 200 OK) and `/tags` (available model tags/metadata).                                                                                    |
| **Simple deployment**               | One‑liner run script or `python -m llm_proxy_rest.rest_api`.                                                                                            |
| **Extensible conversation formats** | Basic chat, conversation with system prompt, and extended conversation with richer options (e.g., temperature, top‑k, custom system prompt).            |
| **Multi‑provider model support**    | Each model can be backed by multiple providers (VLLM, Ollama, OpenAI) defined in `models-config.json`.                                                  |
| **Provider selection abstraction**  | `ProviderChooser` delegates to a configurable strategy, enabling easy swapping of load‑balancing, round‑robin, weighted‑random, etc.                    |
| **Load‑balanced default strategy**  | `LoadBalancedStrategy` distributes requests evenly across providers using in‑memory usage counters.                                                     |
| **Dynamic model handling**          | `ModelHandler` loads model definitions at runtime and resolves the appropriate provider per request.                                                    |
| **Pluggable endpoint architecture** | Automatic discovery and registration of all concrete `EndpointI` implementations via `EndpointAutoLoader`.                                              |
| **Prometheus metrics integration**  | Optional `/metrics` endpoint for latency, error counts, and provider usage statistics.                                                                  |
| **Docker ready**                    | Dockerfile and scripts for containerised deployment.                                                                                                    |

---

## 📦 Quick Start

### 1️⃣ Create & activate a virtual environment

#### Base requirements

> **Prerequisite**: `radlab-ml-utils`
>
> This project uses the
> [radlab-ml-utils](https://github.com/radlab-dev-group/ml-utils)
> library for machine learning utilities
> (e.g., experiment/result logging with Weights & Biases/wandb).
> Install it before working with ML-related parts:
>
> ```bash
> pip install git+https://github.com/radlab-dev-group/ml-utils.git
> ```
>
> For more options and details, see the library README:
> https://github.com/radlab-dev-group/ml-utils

```shell script
python3 -m venv .venv
source .venv/bin/activate

# Only the core library (llm-router-lib).
pip install .

# Core library + API wrapper (llm-router-api).
pip install .[api]
```

#### Prometheus Metrics

To enable Prometheus metrics collection you must install the optional
metrics dependencies:

``` bash
pip install .[api,metrics]
```

Then start the application with the environment variable set:

``` bash
export LLM_ROUTER_USE_PROMETHEUS=1
```

When `LLM_ROUTER_USE_PROMETHEUS` is enabled, the router automatically
registers a **`/metrics`** endpoint (under the API prefix, e.g.
`/api/metrics`). This endpoint exposes Prometheus‑compatible metrics such
as request counts, latencies, and any custom counters defined by the
application. Prometheus servers can scrape this URL to collect runtime
metrics for monitoring and alerting.

### 2️⃣ Minimum required environment variable

``` shell script
./run-rest-api.sh
# or
LLM_ROUTER_MINIMUM=1 python3 -m llm_router_api.rest_api
```

### 📦 Docker

Run the container with the default configuration:

``` bash
docker run -p 5555:8080 quay.io/radlab/llm-router:rc1
```

For more advanced usage you can use a custom launch script, for example:

``` shell script
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
  -e LLM_ROUTER_MODELS_CONFIG=/srv/cfg.json \
  -e LLM_ROUTER_PROMPTS_DIR="/srv/prompts" \
  -v "${PWD}/resources/configs/models-config.json":/srv/cfg.json \
  -v "${PWD}/resources/prompts":/srv/prompts \
  quay.io/radlab/llm-router:rc1
````

---

### 3️⃣ Optional configuration (via environment)

| Variable                          | Description                                                                                                                                                   | Default                                |
|-----------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------|
| `LLM_ROUTER_PROMPTS_DIR`          | Directory containing predefined system prompts.                                                                                                               | `resources/prompts`                    |
| `LLM_ROUTER_MODELS_CONFIG`        | Path to the models configuration JSON file.                                                                                                                   | `resources/configs/models-config.json` |
| `LLM_ROUTER_DEFAULT_EP_LANGUAGE`  | Default language for endpoint prompts.                                                                                                                        | `pl`                                   |
| `LLM_ROUTER_TIMEOUT`              | Timeout (seconds) for llm-router API calls.                                                                                                                   | `0`                                    |
| `LLM_ROUTER_EXTERNAL_TIMEOUT`     | Timeout (seconds) for external model API calls.                                                                                                               | `300`                                  |
| `LLM_ROUTER_LOG_FILENAME`         | Name of the log file.                                                                                                                                         | `llm-router.log`                       |
| `LLM_ROUTER_LOG_LEVEL`            | Logging level (e.g., INFO, DEBUG).                                                                                                                            | `INFO`                                 |
| `LLM_ROUTER_EP_PREFIX`            | Prefix for all API endpoints.                                                                                                                                 | `/api`                                 |
| `LLM_ROUTER_MINIMUM`              | Run service in proxy‑only mode (boolean).                                                                                                                     | `False`                                |
| `LLM_ROUTER_IN_DEBUG`             | Run server in debug mode (boolean).                                                                                                                           | `False`                                |
| `LLM_ROUTER_BALANCE_STRATEGY`     | Strategy used to balance routing between LLM providers. Allowed values are `balanced`, `weighted`, and `dynamic_weighted` as defined in `constants_base.py`.  | `balanced`                             |
| `LLM_ROUTER_SERVER_TYPE`          | Server implementation to use (`flask`, `gunicorn`, `waitress`).                                                                                               | `flask`                                |
| `LLM_ROUTER_SERVER_PORT`          | Port on which the server listens.                                                                                                                             | `8080`                                 |
| `LLM_ROUTER_SERVER_HOST`          | Host address for the server.                                                                                                                                  | `0.0.0.0`                              |
| `LLM_ROUTER_SERVER_WORKERS_COUNT` | Number of workers (used in case when the selected server type supports multiworkers)                                                                          | `2`                                    |
| `LLM_ROUTER_SERVER_THREADS_COUNT` | Number of workers threads (used in case when the selected server type supports multithreading)                                                                | `8`                                    |
| `LLM_ROUTER_SERVER_WORKER_CLASS`  | If server accepts workers type, its able to set worker class by this environment.                                                                             | `None`                                 |
| `LLM_ROUTER_USE_PROMETHEUS`       | Enable Prometheus metrics collection.** When set to `True`, the router registers a `/metrics` endpoint exposing Prometheus‑compatible metrics for monitoring. | `False`                                |

### 4️⃣ Run the REST API

```shell script
./run-rest-api.sh
# or
LLM_ROUTER_MINIMUM=1 python3 -m llm_router_api.rest_api
```

---

## Provider Selection

The LLM‑router supports **multiple providers** for a single model. Provider selection is handled by
the **ProviderChooser** class, which delegates the choice to a configurable **strategy** implementation.

### Chooser

``` python
from llm_router_api.base.lb.chooser import ProviderChooser
from llm_router_api.base.lb.strategy import LoadBalancedStrategy

# By default the chooser uses the LoadBalancedStrategy
provider_chooser = ProviderChooser(strategy=LoadBalancedStrategy())
```

`ProviderChooser.get_provider(model_name, providers)` receives the model name
and the list of provider configurations (as defined in `models-config.json`) and
returns the chosen provider dictionary.

### Strategy Interface

All strategies must implement `ChooseProviderStrategyI`:

``` python
class ChooseProviderStrategyI(ABC):
    @abstractmethod
    def choose(self, model_name: str, providers: List[Dict]) -> Dict:
        """Select one provider configuration for the given model."""
        raise NotImplementedError
```

### Built‑in Strategy: LoadBalancedStrategy

The default `LoadBalancedStrategy` distributes requests evenly across providers
by keeping an in‑memory usage counter per model/provider pair.

``` python
class LoadBalancedStrategy(ChooseProviderStrategyI):
    def __init__(self) -> None:
        self._usage_counters: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )

    def choose(self, model_name: str, providers: List[Dict]) -> Dict:
        # selects the provider with the smallest usage count
        ...
```

### Current Setting

In **`engine.py`** the Flask engine creates the chooser like this:

``` python
self._provider_chooser = ProviderChooser(strategy=LoadBalancedStrategy())
```

Therefore, unless overridden, the application uses the **load‑balanced** provider
selection strategy out of the box.

### Extending with Custom Strategies

To use a different strategy (e.g., round‑robin, random weighted, latency‑based),
implement `ChooseProviderStrategyI` and pass the instance to `ProviderChooser`:

``` python
from llm_router_api.base.lb.chooser import ProviderChooser
from my_strategies import RoundRobinStrategy

chooser = ProviderChooser(strategy=RoundRobinStrategy())
```

The rest of the code – `ModelHandler`, endpoint implementations, etc. – will
automatically use the chooser you provide.

---

## 🛣️ Endpoints Overview

All endpoints are exposed under the REST API service. Unless stated otherwise, methods are POST and consume/produce
JSON.

### Built-in Text Utilities

- `POST /builtin/generate_questions`
    - **Purpose**: Generate a list of questions for each provided text.
    - **Required**: `texts`, `model_name`
    - **Optional**: `number_of_questions`, `stream`, and other common options
    - **Response**: For each input text returns an array of generated questions.

- `POST /builtin/translate`
    - **Purpose**: Translate input texts to Polish.
    - **Required**: `texts`, `model_name`
    - **Optional**: `stream` and other common options
    - **Response**: Array of objects `{ original, translated }` per input text.

- `POST /builtin/simplify_text`
    - **Purpose**: Simplify input texts (make them easier to read).
    - **Required**: `texts`, `model_name`
    - **Optional**: `stream`, `temperature`, `max_tokens` and other common options
    - **Response**: Array of simplified texts aligned with input order.

### Content Generation

- `POST /builtin/generate_article_from_text`
    - **Purpose**: Generate a short article/news-like snippet from a single text.
    - **Required**: text, `model_name`
    - **Optional**: `temperature`, `max_tokens`, `stream` and other common options
    - **Response**: `{ article_text }`

- `POST /builtin/create_full_article_from_texts`
    - **Purpose**: Create a full article from multiple texts with a guiding user query.
    - **Required**: `user_query`, `texts`, `model_name`
    - **Optional**: `article_type`, `stream`, `temperature`, `max_tokens` and other common options
    - **Response**: `{ article_text }`

### Context QA (RAG-like)

- `POST /builtin/generative_answer`
    - **Purpose**: Answer a question using provided context (list of texts or map of `doc_name -> [texts]`).
    - **Required**: `question_str`, `texts`, `model_name`
    - **Optional**: `question_prompt`, `system_prompt`, `doc_name_in_answer`, `stream` and other common options
    - **Response**: `{ article_text }` where the content is the model’s answer based on the supplied context.

### Streaming vs. Non‑Streaming Responses

- **Streaming (`stream: true` – default)**  
  The proxy opens an HTTP **chunked** connection and forwards each token/segment from the upstream LLM as soon as it
  arrives. Clients can process partial output in real time (e.g., live UI updates).

- **Non‑Streaming (`stream: false`)**  
  The proxy collects the full response from the provider, then returns a single JSON object containing the complete
  text. Use this mode when you need the whole answer before proceeding.

Both modes are supported for every provider that implements the streaming interface (OpenAI, Ollama, vLLM). The `stream`
flag lives in the request schema (`OpenAIChatModel` and analogous models) and is honoured automatically by the proxy.

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

## 🛠️ Development

- **Python**3.10+ (project is tested on 3.10.6)
- All dependencies are listed in `requirements.txt`. Install them inside the virtualenv.
- Run tests with `pytest` (already in the environment).
- To add a new provider, create a class in `llm_proxy_rest/core/api_types` that implements the `BaseProvider` interface
  and register it in `llm_proxy_rest/register/__init__.py`.

---

## 📜 License

See the [LICENSE](LICENSE) file.

---

## 📚 Changelog

See the [CHANGELOG](CHANGELOG.md) for a complete history of changes.