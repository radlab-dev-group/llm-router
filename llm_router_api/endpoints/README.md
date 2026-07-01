## Endpoints Overview

All endpoints are exposed under the REST API service. Unless stated otherwise, methods are POST and consume/produce
JSON.

The default API prefix is `/api` (configurable via `LLM_ROUTER_EP_PREFIX`). Endpoints registered with
`dont_add_api_prefix=True` appear without this prefix (e.g. `/models` instead of `/api/models`).

### Authentication

When `LLM_ROUTER_AUTH_ENABLED=true`, endpoints are divided into **public** and **auth‑required**:

| Scope         | Description                                                 | Env var                            |
|---------------|-------------------------------------------------------------|------------------------------------|
| Public        | Bypass all auth checks — always accessible                  | `LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS` |
| Auth‑required | Return **401 Unauthorized** if no valid API key is provided | `LLM_ROUTER_AUTH_ENABLED=true`     |

Public endpoints (default): `/ping`, `/version`, `/models`, `/`, plus any path matching `/v1{public}` (e.g.
`/v1/models`). All other endpoints require a valid API key with the appropriate policy permission:

| Permission type | What it grants access to                               |
|-----------------|--------------------------------------------------------|
| `chat`          | Chat completions, model listing, responses             |
| `embedding`     | Embeddings endpoints                                   |
| `anthropic`     | Anthropic Messages API (`/v1/messages`)                |
| `ollama`        | Ollama‑style chat completion                           |
| `builtin`       | Built‑in utility endpoints (translate, generate, etc.) |

API keys are checked in order of priority:

1. `Authorization: Bearer <key>` header
2. `x-api-key` header
3. Query parameter `api_key` or `api-key`

---

### Health & Info (public)

- **GET** `/ping` – Simple health‑check, returns `"pong"`.
- **GET** `/version` – Return the router version.
- **GET** `/` – Ollama health endpoint.
- **GET** `/tags` – List available Ollama model tags (public).
- **GET** `/models` – List OpenAI‑compatible models (public).
- **GET** `/v1/models` – List OpenAI‑compatible models (public).
- **GET** `/api/v0/models` – List LM Studio models.
- **GET** `/metrics` – Prometheus metrics endpoint (public; requires `LLM_ROUTER_USE_PROMETHEUS=1`).

### Auth‑required Endpoints

#### Chat completions

- **POST** `/chat/completions` — OpenAI‑style chat completion (requires `chat` permission).
- **POST** `/api/chat/completions` — OpenAI‑style chat completion with prefix (requires `chat` permission).
- **POST** `/v1/chat/completions` — vLLM‑like chat completion (requires `chat` permission).
- **POST** `/api/chat` — Ollama‑style chat completion (requires `ollama` permission).

#### Responses

- **POST** `/responses` — OpenAI‑like responses endpoint (requires `chat` permission).
- **POST** `/v1/responses` — OpenAI‑like responses endpoint v1 (requires `chat` permission).

#### Embeddings

- **POST** `/embeddings` — Standard embeddings (requires `embedding` permission).
- **POST** `/api/embeddings` — Standard embeddings with prefix (requires `embedding` permission).
- **POST** `/v1/embeddings` — OpenAI‑compatible embeddings endpoint (requires `embedding` permission).
- **POST** `/api/embed` — Ollama‑native embeddings endpoint (requires `embedding` permission).

#### Anthropic

- **POST** `/v1/messages` — Anthropic Messages API compatible endpoint (requires `anthropic` permission).

#### Chat & Completions (Built‑in, requires `builtin` permission)

- **POST** `/api/conversation_with_model` — Standard chat endpoint (OpenAI‑compatible payload).
- **POST** `/api/extended_conversation_with_model` — Chat with extended fields support.
- **POST** `/api/generative_answer` — Answer a question using provided context.

#### Utility Endpoints (Built‑in, requires `builtin` permission)

- **POST** `/api/generate_questions` — Generate questions from input texts.
- **POST** `/api/translate` — Translate a list of texts.
- **POST** `/api/simplify_text` — Simplify input texts.
- **POST** `/api/generate_article_from_text` — Generate a short article from a single text.
- **POST** `/api/create_full_article_from_texts` — Generate a full article from multiple texts.

### Streaming vs. Non‑Streaming Responses

- **Streaming (`stream: true` – default)**
  The proxy opens an HTTP **chunked** connection and forwards each token/segment from the upstream LLM as soon as it
  arrives. Clients can process partial output in real time (e.g., live UI updates).

- **Non‑Streaming (`stream: false`)**
  The proxy collects the full response from the provider, then returns a single JSON object containing the complete
  text. Use this mode when you need the whole answer before proceeding.

Both modes are supported for every provider that implements the streaming interface (OpenAI, Ollama, vLLM). The `stream`
flag lives in the request schema (`OpenAIChatModel` and analogous models) and is honoured automatically by the proxy.

### Payload format

**Payload format** follows the OpenAI schema (`model`, `messages`, optional `stream`, etc.) unless a custom endpoint
overrides it.

All endpoints automatically:

- Validate required arguments (via `REQUIRED_ARGS`).
- Resolve the appropriate provider using the configured **load‑balancing strategy**.
- Inject system prompts when `SYSTEM_PROMPT_NAME` is defined.
- Return a JSON response with `{ "status": true, "body": … }` or an error payload.
