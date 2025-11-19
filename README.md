## llm‑router

**LLM Router** is a service that can be deployed on‑premises or in the cloud. 
It adds a layer between any application and the LLM provider. In real time it controls traffic, 
distributes a load among providers of a specific LLM, and enables analysis of outgoing requests 
from a security perspective (masking, anonymization, prohibited content). 
It is an open‑source solution (Apache 2.0) that can be launched instantly by running 
a ready‑made image in your own infrastructure.

- **llm_router_api** provides a unified REST proxy that can route requests to any supported LLM backend (
  OpenAI‑compatible, Ollama, vLLM, LM Studio, etc.), with built‑in load‑balancing, health checks, streaming responses
  and optional Prometheus metrics.
- **llm_router_lib** is a Python SDK that wraps the API with typed request/response models, automatic retries, token
  handling and a rich exception hierarchy, letting developers focus on application logic rather than raw HTTP calls.
- **llm_router_web** offers ready‑to‑use Flask UIs – an anonymizer UI that masks sensitive data and a configuration
  manager for model/user settings – demonstrating how to consume the router from a browser.
- **Plugins** (e.g., the **fast_masker** plugin) deliver a rule‑based text anonymisation engine with a comprehensive set
  of Polish‑specific masking rules (emails, IPs, URLs, phone numbers, PESEL, NIP, KRS, REGON, monetary amounts, dates,
  etc.) and an extensible architecture for custom rules and validators.

All components run on Python 3.10+ using `virtualenv` and require only the listed dependencies, making the suite easy to
install, extend, and deploy in both development and production environments.

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
  -e LLM_ROUTER_REDIS_HOST="192.168.100.67" \
  -e LLM_ROUTER_REDIS_PORT=6379 \
  -e LLM_ROUTER_MODELS_CONFIG=/srv/cfg.json \
  -e LLM_ROUTER_PROMPTS_DIR="/srv/prompts" \
  -v "${PWD}/resources/configs/models-config.json":/srv/cfg.json \
  -v "${PWD}/resources/prompts":/srv/prompts \
  quay.io/radlab/llm-router:rc1
````

---

### 3️⃣ Optional configuration (via environment)

| Variable                                    | Description                                                                                                                                                                    | Default                                |
|---------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------|
| `LLM_ROUTER_PROMPTS_DIR`                    | Directory containing predefined system prompts.                                                                                                                                | `resources/prompts`                    |
| `LLM_ROUTER_MODELS_CONFIG`                  | Path to the models configuration JSON file.                                                                                                                                    | `resources/configs/models-config.json` |
| `LLM_ROUTER_DEFAULT_EP_LANGUAGE`            | Default language for endpoint prompts.                                                                                                                                         | `pl`                                   |
| `LLM_ROUTER_TIMEOUT`                        | Timeout (seconds) for llm-router API calls.                                                                                                                                    | `0`                                    |
| `LLM_ROUTER_EXTERNAL_TIMEOUT`               | Timeout (seconds) for external model API calls.                                                                                                                                | `300`                                  |
| `LLM_ROUTER_LOG_FILENAME`                   | Name of the log file.                                                                                                                                                          | `llm-router.log`                       |
| `LLM_ROUTER_LOG_LEVEL`                      | Logging level (e.g., INFO, DEBUG).                                                                                                                                             | `INFO`                                 |
| `LLM_ROUTER_EP_PREFIX`                      | Prefix for all API endpoints.                                                                                                                                                  | `/api`                                 |
| `LLM_ROUTER_MINIMUM`                        | Run service in proxy‑only mode (boolean).                                                                                                                                      | `False`                                |
| `LLM_ROUTER_IN_DEBUG`                       | Run server in debug mode (boolean).                                                                                                                                            | `False`                                |
| `LLM_ROUTER_BALANCE_STRATEGY`               | Strategy used to balance routing between LLM providers. Allowed values are `balanced`, `weighted`, `dynamic_weighted` and `first_available` as defined in `constants_base.py`. | `balanced`                             |
| `LLM_ROUTER_REDIS_HOST`                     | Redis host for load‑balancing when a multi‑provider model is available.                                                                                                        | `<empty string>`                       |
| `LLM_ROUTER_REDIS_PORT`                     | Redis port for load‑balancing when a multi‑provider model is available.                                                                                                        | `6379`                                 |
| `LLM_ROUTER_SERVER_TYPE`                    | Server implementation to use (`flask`, `gunicorn`, `waitress`).                                                                                                                | `flask`                                |
| `LLM_ROUTER_SERVER_PORT`                    | Port on which the server listens.                                                                                                                                              | `8080`                                 |
| `LLM_ROUTER_SERVER_HOST`                    | Host address for the server.                                                                                                                                                   | `0.0.0.0`                              |
| `LLM_ROUTER_SERVER_WORKERS_COUNT`           | Number of workers (used in case when the selected server type supports multiworkers)                                                                                           | `2`                                    |
| `LLM_ROUTER_SERVER_THREADS_COUNT`           | Number of workers threads (used in case when the selected server type supports multithreading)                                                                                 | `8`                                    |
| `LLM_ROUTER_SERVER_WORKER_CLASS`            | If server accepts workers type, its able to set worker class by this environment.                                                                                              | `None`                                 |
| `LLM_ROUTER_USE_PROMETHEUS`                 | Enable Prometheus metrics collection.** When set to `True`, the router registers a `/metrics` endpoint exposing Prometheus‑compatible metrics for monitoring.                  | `False`                                |
| `LLM_ROUTER_FORCE_ANONYMISATION`            | Enable whole payload anonymisation. Each key and value is aut-anonymized before sending to model provider.                                                                     | `False`                                |
| `LLM_ROUTER_ENABLE_GENAI_ANONYMIZE_TEXT_EP` | Enable builtin endpoint `/api/anonymize_text_genai` which uses genai to anonymize text                                                                                         | `False`                                |

### 4️⃣ Run the REST API

```shell script
./run-rest-api.sh
# or
LLM_ROUTER_MINIMUM=1 python3 -m llm_router_api.rest_api
```

---

## ⚖️ Load Balancing Strategies

The `llm-router` supports various strategies for selecting the most suitable provider
when multiple options exist for a given model. This ensures efficient
and reliable routing of requests. The available strategies are:

### 1. `balanced` (Default)

* **Description:** This is the default strategy. It aims to distribute requests
  evenly across available providers by keeping track of how many times each provider has
  been used for a specific model. It selects the provider that has been used the least.
* **When to use:** Ideal for scenarios where all providers are considered equal
  in terms of capacity and performance. It provides a simple and effective way to balance the load.
* **Implementation:** Implemented in `llm_router_api.base.lb.balanced.LoadBalancedStrategy`.

### 2. `weighted`

* **Description:** This strategy allows you to assign static weights to providers.
  Providers with higher weights are more likely to be selected. The selection is deterministic,
  ensuring that over time, the request distribution closely matches the configured weights.
* **When to use:** Useful when you have providers with different capacities or performance
  characteristics, and you want to prioritize certain providers without needing dynamic adjustments.
* **Implementation:** Implemented in `llm_router_api.base.lb.weighted.WeightedStrategy`.

### 3. `dynamic_weighted`

* **Description:** An extension of the `weighted` strategy. It not only uses weights
  but also tracks the latency between successive selections of the same provider.
  This allows for more adaptive routing, as providers with consistently high latency
  might be de-prioritized over time. You can also dynamically update provider weights.
* **When to use:** Recommended for dynamic environments where provider performance
  can fluctuate. It offers more sophisticated load balancing by considering both
  configured weights and real-time performance metrics (latency).
* **Implementation:** Implemented in `llm_router_api.base.lb.weighted.DynamicWeightedStrategy`.

### 4. `first_available`

* **Description:** This strategy selects the very first provider that is available.
  It uses Redis to coordinate across multiple workers, ensuring that only one
  worker can use a specific provider at a time.
* **When to use:** Suitable for critical applications where you need the fastest
  possible response and want to ensure that a request is immediately handled by any available
  provider, without complex load distribution logic. It guarantees that a provider,
  once taken, is exclusive until released.
* **Implementation:** Implemented in `llm_router_api.base.lb.first_available.FirstAvailableStrategy`.

**When using the** `first_available` load balancing strategy, a **Redis server is required**
for coordinating provider availability across multiple workers.

The connection details for Redis can be configured using environment variables:

```shell
LLM_ROUTER_BALANCE_STRATEGY="first_available" \
LLM_ROUTER_REDIS_HOST="your.machine.redis.host" \
LLM_ROUTER_REDIS_PORT=redis_port \
```

**Installing Redis on Ubuntu**

To install Redis on an Ubuntu system, follow these steps:

1. **Update package list:**

```shell
sudo apt update
```

2. **Install Redis server:**

```shell
sudo apt install redis-server
```

3. **Start and enable Redis service:**
   The Redis service should start automatically after installation.
   To ensure it's running and starts on system boot, you can use the following commands:

``` shell
sudo systemctl status redis-server
sudo systemctl enable redis-server
```

4. **Configure Redis (optional):**
   The default Redis configuration (`/etc/redis/redis.conf`) is usually sufficient
   to get started. If you need to adjust settings (e.g., address, port),
   edit this file. After making configuration changes, restart the Redis server:

```shell
sudo systemctl restart redis-server
```

---

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