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

```shell script
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2️⃣ Minimum required environment variable

```shell script
export LLM_PROXY_API_MINIMUM=1
```

### 3️⃣ Optional configuration (via environment)

| Variable                            | Purpose                                                    | Example                                |
|-------------------------------------|------------------------------------------------------------|----------------------------------------|
| `LLM_PROXY_API_LOG_FILENAME`        | Log file location                                          | `llm-proxy-rest.log`                   |
| `LLM_PROXY_API_LOG_LEVEL`           | Logging verbosity (`DEBUG`, `INFO`, `WARN`, `ERROR`)       | `INFO`                                 |
| `LLM_PROXY_API_TIMEOUT`             | Global request timeout (seconds)                           | `300`                                  |
| `LLM_PROXY_API_EP_PREFIX`           | URL prefix for all endpoints                               | `/api`                                 |
| `LLM_PROXY_API_DEFAULT_EP_LANGUAGE` | Default language for built‑in prompts                      | `pl`                                   |
| `LLM_PROXY_API_PROMPTS_DIR`         | Directory with prompt files                                | `resources/prompts`                    |
| `LLM_PROXY_API_MODELS_CONFIG`       | Path to model configuration JSON                           | `resources/configs/models-config.json` |
| `LLM_PROXY_API_IN_DEBUG`            | Enable DEBUG‑level logging when set to any non‑empty value | `true`                                 |

### 4️⃣ Run the REST API

```shell script
./run-rest-api.sh
# or
LLM_PROXY_API_MINIMUM=1 python3 -m llm_proxy_rest.rest_api
```

---

## 🛣️ Endpoints Overview

All URLs are prefixed by the value of `LLM_PROXY_API_EP_PREFIX` (default **/api**).

| Method | Path                                | Description                                                                                                   | Typical Payload                                                                                                               |
|--------|-------------------------------------|---------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------|
| `POST` | `/chat`                             | Simple chat with a model (OpenAI‑compatible). Returns either streamed chunks or a full response.              | `{ "model": "gpt-4o", "messages": [{ "role": "user", "content": "Hello" }], "stream": true }`                                 |
| `POST` | `/conversation_with_model`          | Chat that automatically injects a language‑aware system prompt from the built‑in prompt library.              | `{ "model_name": "gemini-1.5-pro", "user_last_statement": "Explain recursion.", "language": "en" }`                           |
| `POST` | `/extended_conversation_with_model` | Same as above but with extra generation options (temperature, top‑k, etc.) and optional custom system prompt. | `{ "model_name": "llama3", "user_last_statement": "...", "system_prompt": "...", "temperature": 0.7, "max_new_tokens": 256 }` |
| `GET`  | `/tags`                             | Returns a list of tags/metadata for available models (e.g., provider, supported languages).                   |                                                                                                                               |
| `GET`  | `/ping`                             | Health‑check endpoint – returns `200 OK` if the service is running.                                           |                                                                                                                               |
| `POST` | `/passthrough`                      | Directly forwards a raw request to the underlying provider (useful for custom endpoints).                     |                                                                                                                               |

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

| Config File / Variable                                   | Meaning                                                                                               |
|----------------------------------------------------------|-------------------------------------------------------------------------------------------------------|
| `resources/configs/models-config.json`                   | JSON map of provider → model → default options (e.g., `keep_alive`, `options.num_ctx`).               |
| `LLM_PROXY_API_PROMPTS_DIR`                              | Directory containing prompt templates (`*.prompt`). Sub‑folders are language‑specific (`en/`, `pl/`). |
| `LLM_PROXY_API_DEFAULT_EP_LANGUAGE`                      | Language code used when a prompt does not explicitly specify one.                                     |
| `LLM_PROXY_API_TIMEOUT`                                  | Upper bound for any request to an upstream LLM (seconds).                                             |
| `LLM_PROXY_API_LOG_FILENAME` / `LLM_PROXY_API_LOG_LEVEL` | Logging destinations and verbosity.                                                                   |
| `LLM_PROXY_API_IN_DEBUG`                                 | When set, enables DEBUG‑level logs and more verbose error payloads.                                   |

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