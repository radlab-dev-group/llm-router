## llm‑proxy‑api

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
| **Dynamic model configuration**     | JSON file (`models-config.json`) defines provider, model name, default options and per‑model overrides.                                                 |
| **Pluggable providers**             | New providers are added by implementing the `BaseProvider` interface in `llm_proxy_rest/core/api_types`.                                                |
| **Request validation**              | Pydantic models guarantee correct payloads; errors are returned with clear messages.                                                                    |
| **Structured logging**              | Configurable log level, filename, and optional JSON formatting.                                                                                         |
| **Health & metadata endpoints**     | `/ping` (simple 200 OK) and `/tags` (available model tags/metadata).                                                                                    |
| **Simple deployment**               | One‑liner run script or `python -m llm_proxy_rest.rest_api`.                                                                                            |
| **Extensible conversation formats** | Basic chat, conversation with system prompt, and extended conversation with richer options (e.g., temperature, top‑k, custom system prompt).            |

---

## 📦 Quick Start

### 1️⃣ Create & activate a virtual environment

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
pip install -r requirements.txt
pip install .
```

### 2️⃣ Minimum required environment variable

```shell script
export LLM_ROUTER_MINIMUM=1
```

### 3️⃣ Optional configuration (via environment)

| Variable                          | Description                                                                                                 | Default                                |
|-----------------------------------|-------------------------------------------------------------------------------------------------------------|----------------------------------------|
| `LLM_ROUTER_PROMPTS_DIR`          | Directory containing predefined system prompts.                                                             | `resources/prompts`                    |
| `LLM_ROUTER_MODELS_CONFIG`        | Path to the models configuration JSON file.                                                                 | `resources/configs/models-config.json` |
| `LLM_ROUTER_DEFAULT_EP_LANGUAGE`  | Default language for endpoint prompts.                                                                      | `pl`                                   |
| `LLM_ROUTER_EXTERNAL_TIMEOUT`     | Timeout (seconds) for external model API calls.                                                             | `300`                                  |
| `LLM_ROUTER_LOG_FILENAME`         | Name of the log file.                                                                                       | `llm-proxy-rest.log`                   |
| `LLM_ROUTER_LOG_LEVEL`            | Logging level (e.g., INFO, DEBUG).                                                                          | `INFO`                                 |
| `LLM_ROUTER_EP_PREFIX`            | Prefix for all API endpoints.                                                                               | `/api`                                 |
| `LLM_ROUTER_MINIMUM`              | Run service in proxy‑only mode (boolean).                                                                   | `False`                                |
| `LLM_ROUTER_IN_DEBUG`             | Run server in debug mode (boolean).                                                                         | `False`                                |
| `LLM_ROUTER_SERVER_TYPE`          | Server implementation to use (`flask`, `gunicorn`, `waitress`).                                             | `flask`                                |
| `LLM_ROUTER_SERVER_PORT`          | Port on which the server listens.                                                                           | `8080`                                 |
| `LLM_ROUTER_SERVER_HOST`          | Host address for the server.                                                                                | `0.0.0.0`                              |
| `LLM_ROUTER_SERVER_WORKERS_COUNT` | Number of workers/threads (used in case when the selected server type supports multiworkers/multithreading) | `4`                                    |

### 4️⃣ Run the REST API

```shell script
./run-rest-api.sh
# or
LLM_ROUTER_MINIMUM=1 python3 -m llm_router_api.rest_api
```

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