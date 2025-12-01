# LLM Router - Open-Source AI Gateway for Local and Cloud LLM Infrastructure

[**LLM Router**](https://llm-router.cloud) is a service that can be deployed on‑premises or in the cloud.
It adds a layer between any application and the LLM provider. In real time it controls traffic,
distributes a load among providers of a specific LLM, and enables analysis of outgoing requests
from a security perspective (masking, anonymization, prohibited content).
It is an open‑source solution (Apache 2.0) that can be launched instantly by running
a ready‑made image in your own infrastructure.

- **llm_router_api** provides a unified REST proxy that can route requests to any supported LLM backend (
  OpenAI‑compatible, Ollama, vLLM, LM Studio, etc.), with built‑in load‑balancing, health checks, streaming responses
  and optional Prometheus metrics.
- **llm_router_lib** is a Python SDK that wraps the API with typed request/response models, automatic retries, token
  handling and a rich exception hierarchy, letting developers focus on application logic rather than raw HTTP calls.
- [**llm_router_web**](https://github.com/radlab-dev-group/llm-router-web) offers ready‑to‑use Flask UIs – an anonymizer
  UI that masks sensitive data and a configuration
  manager for model/user settings – demonstrating how to consume the router from a browser.
- [**llm_router_plugins**](https://github.com/radlab-dev-group/llm-router-plugins) (e.g., the **fast_masker** plugin)
  deliver a rule‑based text anonymisation engine with
  a comprehensive set of Polish‑specific masking rules (emails, IPs, URLs, phone numbers, PESEL, NIP, KRS, REGON,
  monetary amounts, dates, etc.) and an extensible architecture for custom rules and validators.
- [**llm_router_services**](https://github.com/radlab-dev-group/llm-router-services) provides HTTP services that
  implement the core functionality used by the LLM‑Router’s plugin system. The services expose guardrail and masking
  capabilities through Flask applications.

All components run on Python 3.10+ using `virtualenv` and require only the listed dependencies, making the suite easy to
install, extend, and deploy in both development and production environments.

---

## 🧩 Boilerplates

For a detailed explanation of each example’s purpose, structure, and how the boilerplates are organized, see the main
project README:

- **Main README – Boilerplate Overview** – [examples](examples/README.md)
- **LlamaIndex Boilerplate Details** – [README](examples/README_LLAMAINDEX.md)

---

## ✨ Key Features

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

The quick‑start guides for running the full stack with **local models** are included in the repository:

- **Gemma 3 12B‑IT** – [README](examples/quickstart/google-gemma3-12b-it/README.md)
- **Bielik 11B‑v2.3‑Instruct** – [README](examples/quickstart/speakleash-bielik-11b-v2_3-Instruct/README.md)

### 2️⃣ Minimum required environment variable

``` shell script
./run-rest-api.sh
# or
LLM_ROUTER_MINIMUM=1 python3 -m llm_router_api.rest_api
```

---

## 🔐 Auditing

The router can record request‑level events (guard‑rail checks, payload masking, custom logs) in a tamper‑evident,
encrypted form.  
All audit entries are written by the **auditor** module and stored under `logs/auditor/` as GPG‑encrypted files.

For a complete guide—including key generation, encryption workflow, and decryption utilities—see the dedicated
documentation:

➡️ **[Auditing subsystem documentation](llm_router_api/core/auditor/README.md)**


---

## 📦 Docker

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

## 🛠️ Configuration (via environment)

A full list of environment variables is available at the link
[.env list](llm_router_api/README.md#environment-variables)

---

## ⚖️ Load Balancing Strategies

The current list of available strategies, the interface description,
and an example extension can be found at the link
[load balancing strategies](llm_router_api/LB_STRATEGIES.md#load-balancing-strategies)


---

## 🛣️ Endpoints Overview

The list of endpoints—categorized into built‑in, provider‑dependent, and extended endpoints—and
a description of the streaming mechanisms can be found at the link:
[load endpoints overview](llm_router_api/endpoints/README.md#endpoints-overview)

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

- **Python**3.10+ (project is tested on 3.10.6)
- All dependencies are listed in `requirements.txt`. Install them inside the virtualenv.
- To add a new provider, create a class in `llm_proxy_rest/core/api_types` that implements the `BaseProvider` interface
  and register it in `llm_proxy_rest/register/__init__.py`.

---

## 📜 License

See the [LICENSE](LICENSE) file.

---

## 📚 Changelog

See the [CHANGELOG](CHANGELOG.md) for a complete history of changes.