## Endpoints Overview

All endpoints are exposed under the REST API service. Unless stated otherwise, methods are POST and consume/produce
JSON.

### Health & Info

- **GET** `LLM_ROUTER_EP_PREFIX/ping` – Simple health‑check, returns `"pong"`.
- **GET** `LLM_ROUTER_EP_PREFIX/` – Ollama health endpoint.

### Provider‑Specific

- **GET** `LLM_ROUTER_EP_PREFIX/tags` – List available Ollama model tags.
- **GET** `LLM_ROUTER_EP_PREFIX/models` – List OpenAI‑compatible models.
- **POST** `LLM_ROUTER_EP_PREFIX/api/v0/models` – List LM Studio models.
- **POST** `LLM_ROUTER_EP_PREFIX/api/chat` – Ollama‑style chat completion.
- **POST** `LLM_ROUTER_EP_PREFIX/api/chat/completions` – OpenAI‑style chat completion.
- **POST** `LLM_ROUTER_EP_PREFIX/chat/completions` – OpenAI‑style chat completion (alternative path).
- **POST** `LLM_ROUTER_EP_PREFIX/v1/chat/completions` – vLLM‑like chat completion.
- **POST** `LLM_ROUTER_EP_PREFIX/v1/responses` – OpenAI‑like responsesendpoint.
- **POST** `LLM_ROUTER_EP_PREFIX/api/embeddings` – Standard embeddings endpoint.
- **POST** `LLM_ROUTER_EP_PREFIX/v1/embeddings` – OpenAI‑compatible embeddings endpoint.
- **POST** `LLM_ROUTER_EP_PREFIX/api/embed` – Ollama‑native embeddings endpoint.

### Chat & Completions (Built‑in)

- **POST** `LLM_ROUTER_EP_PREFIX/api/conversation_with_model` – Standard chat endpoint (OpenAI‑compatible payload).
- **POST** `LLM_ROUTER_EP_PREFIX/api/extended_conversation_with_model` – Chat with extended fields support.
- **POST** `LLM_ROUTER_EP_PREFIX/api/generative_answer` – Answer a question using provided context.

### Utility Endpoints (Built‑in)

- **POST** `LLM_ROUTER_EP_PREFIX/api/generate_questions` – Generate questions from input texts.
- **POST** `LLM_ROUTER_EP_PREFIX/api/translate` – Translate a list of texts.
- **POST** `LLM_ROUTER_EP_PREFIX/api/simplify_text` – Simplify input texts.
- **POST** `LLM_ROUTER_EP_PREFIX/api/generate_article_from_text` – Generate a short article from a single text.
- **POST** `LLM_ROUTER_EP_PREFIX/api/create_full_article_from_texts` – Generate a full article from multiple texts.

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
