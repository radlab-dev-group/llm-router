## Endpoints Overview

> **Creating new endpoints?** See the [Endpoint Development Guide](../docs/ENDPOINT_DEV.md)
> (`llm_router_api/docs/ENDPOINT_DEV.md`).

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

Public endpoints: `LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS`, **default `/metrics,/health`** — and for every entry, `/v1{entry}`
as well. The list is compared against the full request path, so a bare entry never matches a prefixed route: endpoints
built with `dont_add_api_prefix=False` live under `LLM_ROUTER_EP_PREFIX` (`/api` by default) and need the prefixed entry
(`LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS="/metrics,/health,/api/ping"`). Everything else requires a valid API key with the
appropriate policy permission:

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
3. Query parameters `api_key` / `api-key` are **rejected** (logged as a warning) — use one of the headers

---

### Health & Info

Public by default (`LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS="/metrics,/health"`), reachable without a key whatever
`LLM_ROUTER_AUTH_ENABLED` says:

- **GET** `/health` – Router health check → `{"status": true, "body": "healthy", "stream": false}`.
- **GET** `/metrics` – Prometheus metrics (requires `LLM_ROUTER_USE_PROMETHEUS=1`). Registered straight on the app, so the
  path is literal `/metrics` — `LLM_ROUTER_EP_PREFIX` does not apply.

Everything else below needs a key once auth is on; the permission in brackets comes from
`_ENDPOINT_PERMISSION_MAP`:

- **GET** `/models` – List OpenAI‑compatible models (`chat`).
- **GET** `/v1/models` – List OpenAI‑compatible models, v1 (`chat`).
- **GET** `/` – Ollama health endpoint → `Ollama is running` (`chat`).
- **GET** `/api/ping` – Simple health‑check → `{"status": true, "body": "pong", "stream": false}` (`builtin`).
- **GET** `/api/version` – Return the router version → `{"version": "<semver>", "stream": false}` (`builtin`); this is the
  path `llm_router_lib` clients call.
- **GET** `/api/tags` – List available Ollama model tags (`chat`).
- **GET** `/api/v0/models` – List LM Studio models (`chat`).

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
- **POST** `/api/polarity_3c` — Detect 3-class polarity (`ambivalent`, `positive`, `negative`) for input texts.
- **POST** `/api/translate` — Translate a list of texts.
- **POST** `/api/simplify_text` — Simplify input texts.
- **POST** `/api/generate_label` — Generate a category name (label) from input texts. Returns a single, concise name
  capturing the common essence of the texts.
- **POST** `/api/generate_article_from_text` — Generate a short article from a single text.
- **POST** `/api/create_full_article_from_texts` — Generate a full article from multiple texts.

#### Masking Endpoint (Built‑in, requires `builtin` permission when auth enabled)

- **POST** `/api/fast_text_mask` — Mask PII in plain text using the built‑in FastText masking ruleset. Accepts a `text`
  field in the JSON body and returns masked content. Does not use guardrails or provider routing
  (`EP_DONT_NEED_GUARDRAIL_AND_MASKING = True`).

### Streaming vs. Non‑Streaming Responses

- **Streaming (`stream: true` – default)**
  The proxy opens an HTTP **chunked** connection and forwards each token/segment from the upstream LLM as soon as it
  arrives. Clients can process partial output in real time (e.g., live UI updates).

- **Non‑Streaming (`stream: false`)**
  The proxy collects the full response from the provider, then returns a single JSON object containing the complete
  text. Use this mode when you need the whole answer before proceeding.

Both modes are supported for every provider that implements the streaming interface (OpenAI, Ollama, vLLM, Anthropic, Vertex AI). The `stream`
flag lives in the request schema (`OpenAIChatModel` and analogous models) and is honoured automatically by the proxy.

### Payload format

**Payload format** follows the OpenAI schema (`model`, `messages`, optional `stream`, etc.) unless a custom endpoint
overrides it.

All endpoints automatically:

- Validate required arguments (via `REQUIRED_ARGS`).
- Resolve the appropriate provider using the configured **load‑balancing strategy**.
- Inject system prompts when `SYSTEM_PROMPT_NAME` is defined.
- Return a JSON response with `{ "status": true, "body": … }` or an error payload.
