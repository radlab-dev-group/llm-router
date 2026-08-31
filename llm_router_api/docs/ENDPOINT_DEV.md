# Endpoint Development Guide

This guide explains how to create, configure and extend REST **endpoints (EP)** in `llm_router_api`.

> **Related pages:** endpoint catalog — [`../endpoints/README.md`](../endpoints/README.md) ·
> models config — [`MODELS_CONFIG.md`](MODELS_CONFIG.md) ·
> load balancing — [`LB_STRATEGIES.md`](LB_STRATEGIES.md) ·
> environment variables — [`ENV_DEFINITIONS.md`](ENV_DEFINITIONS.md)

---

## 1. Class hierarchy and base variants

All endpoint code lives in `llm_router_api/endpoints/endpoint_i.py` (plus
[`passthrough.py`](../endpoints/passthrough.py)). The hierarchy is:

```
SecureEndpointI                 – security scaffolding (masking, guardrails, audit, metrics)
└── EndpointI (ABC)             – abstract base: API surface + validation, no run_ep
    └── EndpointWithHttpRequestI (ABC) – full proxy implementation (run_ep, HTTP, streaming)
        └── PassthroughI (ABC)  – "forward as-is" base for OpenAI‑compatible endpoints
```

### `EndpointI` (abstract base)

* Defines the general API and argument validation, but **does not implement** `run_ep`.
* Abstract methods that every concrete endpoint must implement:
    * `run_ep(params)` – execute the endpoint logic for a request.
    * `prepare_payload(params)` – convert raw request parameters into the payload understood by the downstream backend
      (or the final response body).
* Class attributes (defaults):
    * `METHODS = ["GET", "POST"]` – supported HTTP verbs.
    * `REQUIRED_ARGS = []` – parameter names that **must** be present (see §5).
    * `OPTIONAL_ARGS = []` – accepted but optional parameter names (see §5).
    * `SYSTEM_PROMPT_NAME = {"pl": None, "en": None}` – per‑language system‑prompt ids (see §3).
* Useful helpers:
    * `_check_required_params(params)` – raises `ValueError` (→ HTTP 400) when a required key is missing.
    * `_resolve_prompt_name(params, map_prompt, prompt_str_force, prompt_str_postfix)` – builds the final system prompt
      (see §3).
    * `_get_choices_from_response(response)` – parses a `requests.Response` into `(json_body, choices, assistant_text)`;
      handles both OpenAI‑style (`choices`) and Ollama‑style (`message`) bodies.
    * `return_response_ok(body)` / `return_response_not_ok(body)` – standardized JSON response envelopes.
* The constructor validates the endpoint definition at startup:
    * `api_types` must be non‑empty and intersect the global `API_TYPES` list (`"builtin"`, `"openai"`, `"ollama"`,
      `"lmstudio"`, `"vllm"`, `"anthropic"` — defined in
      `llm_router_api/core/api_types/dispatcher.py`), otherwise `RuntimeError`.
    * `method` must be one of `METHODS`, otherwise `ValueError`.

### `EndpointWithHttpRequestI` (proxy base)

Extends `EndpointI` with the full outbound‑HTTP implementation:

* Complete `run_ep` implementation (see §2 for the cycle).
* Outbound HTTP via `HttpRequestExecutor` (`endpoints/httprequest.py`) and retry orchestration via `HttpDispatch`
  (`endpoints/http_dispatch.py`).
* `timeout` – seconds after which outbound HTTP calls are aborted. Defaults to `EXTERNAL_API_TIMEOUT` (300 s, env
  `LLM_ROUTER_EXTERNAL_TIMEOUT`).
* System‑prompt injection into `messages` and streaming (NDJSON) support.

### `PassthroughI` (passthrough base)

* Sets `REQUIRED_ARGS = None`, `OPTIONAL_ARGS = None`, `SYSTEM_PROMPT_NAME = None`.
* `prepare_payload(params)` returns `params or {}` unchanged (decorated with
  `@EP.response_time`), so the request is forwarded verbatim.
* Useful for OpenAI‑compatible endpoints where you simply forward what arrives.

**Why do the endpoints in `endpoints/builtin/openai.py` subclass `PassthroughI`?**

OpenAI‑compatible endpoints need minimal logic – just forward the incoming request.
`PassthroughI` removes the boilerplate (no required arguments, no system prompt, ready‑made proxy `run_ep`). The
concrete classes (`OpenAICompletionHandler`, `OpenAIResponsesHandler`,
`OpenAIModelsHandler`, …) only add a `prepare_response_function`
that normalizes non‑OpenAI responses (Ollama / Anthropic) into the OpenAI shape.

---

## 2. Execution cycle – what `run_ep` does in `EndpointWithHttpRequestI`

In short, `run_ep(params)` performs the following steps (implementation: `EndpointWithHttpRequestI.run_ep` in
`endpoints/endpoint_i.py`):

1. **Start timer** – `self._start_time = time.time()`.
2. **Prepare the payload** – `params = self._prepare_incoming_payload(params)`:
   calls your `prepare_payload(params)` (endpoint logic) and then runs the configured *utils plugins* pipeline (when
   `UTILS_PLUGINS_PIPELINE` is set).
3. **Guardrail check** – `_is_request_guardrail_safe(payload)`: blocked requests return the guardrail response
   immediately (streaming‑aware). Endpoints that do not need this can set
   `EP_DONT_NEED_GUARDRAIL_AND_MASKING = True` (e.g. the `ApiVersion` endpoint).
4. **Secure the payload** – `_secure_payload(params)`: applies PII masking (when enabled) and strips internal‑only keys
   (`_clear_payload` removes `response_time`, …) so they are never forwarded to the provider.
5. **Extract prompt overrides** – `_extract_prompt_overrides(params)` pops the internal keys
   `map_prompt`, `prompt_str_force`, `prompt_str_postfix` from the payload dict (see §3).
6. **Direct return** – if `self.direct_return` is `True`, the prepared payload is returned verbatim and **no** provider
   call is made (useful for endpoints that produce local answers, e.g. `/version`).
7. **Resolve the provider** – `_resolve_provider(params, options)` picks the model/provider via
   `ModelHandler` and the load‑balancing strategy. The model name is read from the payload using
   `MODEL_NAME_PARAMS = ["model_name", "model"]`
   (constant in `llm_router_lib/data_models/constants.py`). If no model is found →
   `ValueError` (→ 400).
8. **Adapt params to the provider** – `_prepare_params_for_provider(...)` rewrites the payload for the concrete
   `api_type` (e.g. OpenAI‑compatible parameter filtering via
   `_filter_params_to_acceptable`).
9. **Normalize message roles** – `_ensure_alternating_roles(params)` merges consecutive same‑role messages. **Skipped**
   for `call_for_each_user_msg` endpoints, which deliberately build one `user` message per source text.
10. **Simple‑proxy decision**:

    ```python
    simple_proxy = (
        not self.REQUIRED_ARGS
        and api_model_provider.api_type.lower() in self._ep_types_str
    )
    ```

    If the endpoint declares no required arguments *and* the chosen provider's API type matches one of the endpoint's
    `api_types`, the endpoint behaves as a **direct proxy** to the model's own endpoint (e.g.`POST /v1/chat/completions`
    on an OpenAI‑compatible provider).
11. **Resolve the system prompt** – `_resolve_prompt_name(...)` (see §3) returns
    `(prompt_name, prompt_str)`.
12. **Compute the target URL** – `ApiTypesDispatcher.get_proper_endpoint(api_type, endpoint_url)`
    maps the endpoint fragment to the canonical URL of the provider's API (keywords `completions` / `responses` /
    `embeddings` select the target; anything else → chat).
13. **Dispatch**:
    * `simple_proxy` and non‑streaming → `_return_response_or_rerun(...)`:
      POST/GET to the provider with the final payload; on retryable statuses it retries with a *different* provider
      (exponential backoff + jitter, see `HttpDispatch`);
    * `stream: true` → `_dispatch_streaming(...)`: returns an **NDJSON iterator**
      (chunked transfer). **Not supported** for `call_for_each_user_msg` endpoints – raises
      `ValueError: "Streaming is available only for single message"`;
    * otherwise → `_dispatch_non_streaming(...)`.
14. **Response normalization** – `return_http_response(response)`:
    if `self._prepare_response_function` is set it is used to transform the raw
    `requests.Response` into the final body; otherwise `response.json()`; a non‑JSON body is wrapped as
    `{"raw_response": <text>}`.
15. **Error mapping** – `ValueError` (missing required args, unknown model, …) propagates to the Flask registrar, which
    maps it to an **HTTP 400** with the message. Any other exception is logged and converted to an error payload via
    `return_response_not_ok(e)`.
16. **Cleanup** – in `finally`, the chosen provider is released (`unset_model`), unless the response was streaming
    (legacy behavior).

---

## 3. System prompt and content overrides – how the fields work

### `SYSTEM_PROMPT_NAME`

A dict mapping language codes to prompt ids:

```python
SYSTEM_PROMPT_NAME = {
    "pl": "builtin/system/pl/generate-questions",
    "en": "builtin/system/en/generate-questions",
}
```

Prompt files live under `PROMPTS_DIR` (default `resources/prompts`, env
`LLM_ROUTER_PROMPTS_DIR`), e.g. `resources/prompts/builtin/system/pl/generate-questions.prompt`. The id used in
`SYSTEM_PROMPT_NAME` is the file path **without** the `.prompt` extension, relative to `PROMPTS_DIR`.

At runtime `_resolve_prompt_name` (in `EndpointI`):

1. picks the language from the payload's `language` key (constant `LANGUAGE_PARAM`), falling back to
   `DEFAULT_EP_LANGUAGE` (env `LLM_ROUTER_DEFAULT_EP_LANGUAGE`, default `"pl"`);
2. loads the prompt text through `PromptHandler.get_prompt(prompt_name)` (requires a
   `prompt_handler` to be injected);
3. applies `map_prompt` – a `{placeholder: replacement}` dict (e.g. injecting a question count or user content into
   `##QUESTION_NUM_STR##`);
4. appends `prompt_str_postfix` (extra trailing instruction);
5. if `prompt_str_force` is a non‑empty string, it **replaces** the whole file‑based prompt (the file is never loaded).

**Effective precedence:**

```
prompt_str_force  (full override)
    >  SYSTEM_PROMPT_NAME file (selected by language)
map_prompt        (placeholder substitution, applied to either)
prompt_str_postfix (appended to the final text)
```

### How overrides are passed – payload keys (current mechanism)

Prompt overrides are passed **as keys in the dict returned by `prepare_payload`**, not as instance attributes. They are
popped by `_extract_prompt_overrides` and therefore **never**
forwarded to the provider:

```python
@EP.require_params
def prepare_payload(self, params):
    ...
    payload = {
        "model": options.model_name,
        "messages": [...],
        # internal prompt‑override keys (popped before the HTTP call):
        "map_prompt": {
            "##MAX_POINTS##": str(options.max_points),
            "##STYLE_HINT##": options.style_hint or "neutral",
        },
        # "prompt_str_postfix": "Answer only.",        # optional
        # "prompt_str_force": full_prompt_string,       # optional – replaces the file
    }
    return payload
```

The built‑in `TextListUtilityEndpoint` (in `endpoints/builtin/builtin_utils.py`) shows the canonical pattern: a
`build_map_prompt(payload)` hook returns the mapping, and the base class stores it under `payload["map_prompt"]` (see
`GenerateQuestions`, which substitutes
`##QUESTION_NUM_STR##`).

**When to use which:**

* `map_prompt` – when you want to substitute placeholders inside a prompt file (e.g. `##QUESTION_NUM_STR##`,
  `##MAX_POINTS##`).
* `prompt_str_postfix` – when the endpoint must append a final rule/note to the system prompt.
* `prompt_str_force` – when you want to ignore the prompt files entirely and provide the full prompt inline (e.g. it
  comes from a `system_prompt` request parameter).

**Effect on execution:** the resulting text is injected by `HttpRequestExecutor.call_http_request`
as the first message – `{"role": "system", "content": <prompt_str>}`. For
`call_for_each_user_msg` endpoints the system message is paired with **each** individual
`user` message separately.

---

## 4. Hooks – `_prepare_response_function`

`_prepare_response_function` (exposed via the read‑only `prepare_response_function` property) is an optional hook for
post‑processing the HTTP response:

* **Single‑request mode** – if set, it is called with the raw `requests.Response` and its return value replaces
  `response.json()` (see `OpenAIResponseHandler.prepare_response_function`, which converts Ollama/Anthropic responses
  into the OpenAI shape).
* **`call_for_each_user_msg=True` mode – MANDATORY** – the executor raises
  `RuntimeError("_prepare_response_function must be implemented when calling api for each user
  message")` when it is missing. The function receives the **list** of responses and the **list**
  of user‑message contents (in order) and must return the final aggregated structure:

  ```python
  self._prepare_response_function = lambda responses, contents: {...}
  ```

  (The per‑message flow is implemented in
  `HttpRequestExecutor._call_for_each_user_message` and is **POST‑only**.)

**Effect:** the hook fully controls the shape of the JSON response (flattening `choices` →
`content`, computing `generation_time`, mapping answers back to the original texts, …).

---

## 5. Parameter validation – `REQUIRED_ARGS` and `OPTIONAL_ARGS`

* `REQUIRED_ARGS` – list of parameter names the client **must** send.
  `@EP.require_params` (decorator in `core/decorators.py`) calls `_check_required_params`, which raises `ValueError` →
  **HTTP 400** when any key is missing. **If the list is empty (or `None`), the endpoint may run in *simple‑proxy*mode**
  (see §2, step 10) – this is the mechanism `PassthroughI` relies on.
* `OPTIONAL_ARGS` – informational list of accepted optional parameters (a semantic contract for validators / data
  models). The built‑in endpoints validate the full payload with Pydantic models from `llm_router_lib.data_models`inside
  `prepare_payload`.

**Effect:** declaring `REQUIRED_ARGS` directly changes the `run_ep` path – an empty list activates the "simple proxy"
logic when the provider's API type matches `api_types`.

---

## 6. Endpoint constructor parameters – what they set

Summary of the constructor of `EndpointI` + `EndpointWithHttpRequestI`:

| Parameter                              | Default                                                           | Effect                                                                                                                                                                                              |
|----------------------------------------|-------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `ep_name`                              | *(required)*                                                      | URL fragment of the endpoint (e.g. `"chat/completions"`). The registrar prepends the global API prefix unless disabled.                                                                             |
| `api_types`                            | *(required)*                                                      | List of supported API types, e.g. `["builtin"]`, `["openai", "ollama"]`. Must intersect the global `API_TYPES` (else `RuntimeError`). Used for validation, simple‑proxy matching, and URL dispatch. |
| `method`                               | `"POST"`                                                          | `"GET"` or `"POST"`; affects parameter extraction and `requests.get/post`.                                                                                                                          |
| `logger_level`                         | `REST_API_LOG_LEVEL` (env `LLM_ROUTER_LOG_LEVEL`, default `INFO`) | Logging level for this endpoint.                                                                                                                                                                    |
| `logger_file_name`                     | `"llm-router.log"`                                                | Log file for this endpoint.                                                                                                                                                                         |
| `prompt_handler`                       | `None`                                                            | `PromptHandler` instance; required to load prompts from `PROMPTS_DIR` when `SYSTEM_PROMPT_NAME` is used.                                                                                            |
| `model_handler`                        | `None`                                                            | `ModelHandler` instance; required to resolve model names → host / api type / model name. Without it a proxy endpoint cannot pick the backend.                                                       |
| `dont_add_api_prefix`                  | `False`                                                           | `True` → the route is registered **without** the global prefix (`LLM_ROUTER_EP_PREFIX`, default `/api`). Use for `"models"`, `"v1/…"`, etc.                                                         |
| `direct_return`                        | `False`                                                           | `True` → `run_ep` returns the `prepare_payload` result verbatim, **no** provider call. For endpoints producing local/static answers.                                                                |
| `timeout` (`EndpointWithHttpRequestI`) | `EXTERNAL_API_TIMEOUT` (300 s, env `LLM_ROUTER_EXTERNAL_TIMEOUT`) | Timeout in seconds for outbound HTTP calls.                                                                                                                                                         |
| `call_for_each_user_msg`               | `False`                                                           | `True` → split `messages` into one request per `user` message and aggregate the results with `_prepare_response_function(responses, contents)`.                                                     |

---

## 7. How to add a new endpoint – step by step

1. **Choose the base class:**
    * Forwarding only (OpenAI‑like) → subclass `PassthroughI`.
    * Processing needed (validation, prompt building, field mapping) → subclass
      `EndpointWithHttpRequestI` (or an existing shared base such as
      `TextListUtilityEndpoint`).

2. **Set the class attributes:**
    * `REQUIRED_ARGS` and `OPTIONAL_ARGS` (list or `None`).
    * `SYSTEM_PROMPT_NAME = {"pl": "...", "en": "..."}` or `None`.
    * Optionally `EP_DONT_NEED_GUARDRAIL_AND_MASKING = True` for endpoints that must skip guardrail/masking (e.g.
      version/health endpoints).

3. **Add the prompt files** (when using `SYSTEM_PROMPT_NAME`):
   `resources/prompts/builtin/system/pl/<name>.prompt` and
   `resources/prompts/builtin/system/en/<name>.prompt`.

4. **Implement `prepare_payload(self, params)`** (usually decorated with `@EP.require_params`):
    * validate and transform the input (a Pydantic model from `llm_router_lib.data_models` is the recommended pattern);
    * build the backend payload:
        - set `"model"` (typically from `"model_name"`),
        - set `"messages"` (the system prompt is added automatically – do not add it yourself),
        - set `"stream"` (`True`/`False`);
    * if needed, add the prompt‑override keys (`map_prompt`, `prompt_str_postfix`,
      `prompt_str_force`) to the returned dict (see §3);
    * if the endpoint answers locally / with a static payload – set `self.direct_return = True`
      (or pass `direct_return=True` in the constructor) and return the ready object (dict/str).

5. **Per‑user‑message mode (batches over many texts)?**
    * pass `call_for_each_user_msg=True` in the constructor;
    * define `self._prepare_response_function` – it receives the list of responses and the list of user‑message contents
      and builds the final result.

6. **Instantiate with a default‑friendly constructor:** give every constructor parameter a default value, because
   `EndpointAutoLoader.instantiate_with_defaults` instantiates discovered classes with exactly these kwargs:
   `logger_level`, `logger_file_name`, `model_handler`,
   `prompt_handler`.

7. **Auto‑registration:**
    * `EndpointAutoLoader` (`register/auto_loader.py`) walks the endpoint package, collects all
      `EndpointI` subclasses and instantiates them (or from an explicit config list via
      `instantiate_from_config`).
    * The Flask registrar then registers the route from `ep_name`, prepending the global API prefix
      (`LLM_ROUTER_EP_PREFIX`, default `/api`) unless `dont_add_api_prefix=True`.

---

## 8. Most common usage patterns

### 8.1 Simple OpenAI‑compatible proxy

* Subclass `PassthroughI` (see `OpenAIResponseHandler` in `endpoints/builtin/openai.py`).
* `REQUIRED_ARGS = None`, `SYSTEM_PROMPT_NAME = None`.
* `prepare_payload` does nothing (returns `params or {}`).
* `api_types` = the backend types you want to support (e.g. `OPENAI_COMPATIBLE_PROVIDERS`).
* Add a `prepare_response_function` if the upstream body needs normalization (Ollama/Anthropic → OpenAI).

### 8.2 Endpoint with a built‑in system prompt

* Subclass `EndpointWithHttpRequestI`.
* Set `SYSTEM_PROMPT_NAME` (pl/en) and add the two prompt files under `resources/prompts`.
* In `prepare_payload`, set the `map_prompt` / `prompt_str_postfix` / `prompt_str_force` keys as needed and rebuild
  `"messages"` and `"model"`.
* For multiple calls – `call_for_each_user_msg=True` + `_prepare_response_function`
  (see `TextListUtilityEndpoint` and its `GenerateQuestions` child for the full pattern).

### 8.3 Local / static endpoint

* `direct_return=True` (constructor or set inside `prepare_payload`, as in `ApiVersion`).
* Return the final dict/str from `prepare_payload` – no provider is contacted.

---

## 9. Quick field reference

| Field / parameter                    | Where                                    | Effect                                                                                                                                        |
|--------------------------------------|------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| `SYSTEM_PROMPT_NAME`                 | class attribute                          | Prompt ids per language (`pl`/`en`); decides which file `_resolve_prompt_name` loads. `None` disables system prompts.                         |
| `map_prompt` (payload key)           | `prepare_payload` return value           | `{placeholder: text}` substitutions applied to the system prompt (e.g. `##MAX_POINTS##`). Popped before the HTTP call.                        |
| `prompt_str_postfix` (payload key)   | `prepare_payload` return value           | Text appended after the resolved system prompt. Popped before the HTTP call.                                                                  |
| `prompt_str_force` (payload key)     | `prepare_payload` return value           | Non‑empty string replaces the whole system prompt (file is not loaded). Popped before the HTTP call.                                          |
| `_prepare_response_function`         | instance attribute                       | Hook for post‑processing: single `response` or `(responses, contents)`; decides the final JSON shape. Mandatory for `call_for_each_user_msg`. |
| `REQUIRED_ARGS`                      | class attribute                          | Missing keys → `ValueError` → 400. Empty list ⇒ simple‑proxy eligibility.                                                                     |
| `OPTIONAL_ARGS`                      | class attribute                          | Informational contract of optional parameters (Pydantic models do the real validation).                                                       |
| `direct_return`                      | constructor / instance                   | Return the `prepare_payload` result without a provider call.                                                                                  |
| `call_for_each_user_msg`             | constructor                              | One request per `user` message; POST‑only; no streaming; requires the response hook.                                                          |
| `dont_add_api_prefix`                | constructor                              | Register the route without the global `/api` prefix.                                                                                          |
| `timeout`                            | constructor (`EndpointWithHttpRequestI`) | Outbound HTTP timeout in seconds (default 300).                                                                                               |
| `EP_DONT_NEED_GUARDRAIL_AND_MASKING` | class attribute                          | Skip guardrail checks and PII masking for this endpoint.                                                                                      |

---

## 10. Practical notes

* **Streaming**
    * If the payload has `"stream": True` and the endpoint runs as simple proxy (or generic dispatch), `run_ep` switches
      to streaming mode and returns an **NDJSON iterator**
      (chunked transfer, `text/event-stream`‑style lines).
    * Streaming is **not available** with `call_for_each_user_msg=True` – the executor raises
      `ValueError: "Streaming is available only for single message"`.
* **URL prefix**
    * `dont_add_api_prefix=True` → the endpoint is published without the global prefix (`LLM_ROUTER_EP_PREFIX`, default
      `/api`) – e.g. `"models"` → `GET /models`.
* **Models**
    * Provider resolution requires one of the `MODEL_NAME_PARAMS` keys – `"model"` or
      `"model_name"` (from `llm_router_lib/data_models/constants.py`). Make sure
      `prepare_payload` normalizes the model field (the repo convention is to set `"model"` from
      `"model_name"` before dispatch).
* **Retries** – outbound calls are orchestrated by `HttpDispatch`: retryable HTTP statuses are re‑issued against a
  *different* provider with exponential backoff + jitter (see
  `endpoints/http_dispatch.py`); transport errors are retried the same way.
* **Guards** – every payload passes the guardrail check and (optionally) PII masking before the provider call, unless
  `EP_DONT_NEED_GUARDRAIL_AND_MASKING = True` is set.
* **Response envelope** – `@EP.response_time` (and the base `prepare_payload` of `PassthroughI`)
  add a `response_time` field (seconds) to dict results; it is stripped again before forwarding (`_clear_payload`).
* **Per‑message mode** – only `"user"`‑role messages are dispatched (one call each, with the shared system message);
  `GET` is not supported.

---

## Worked example: `BatchFileSummaries` (per‑file summaries)

> Full worked endpoint (translated from the Polish guide). Goal: accept a list of "files"
> (already extracted text content), process **each one separately** against the model, and return
> structured summaries + key points. Uses the per‑message mode (one request per file) and
> aggregates the results.

**Specification**

* Route: `POST /api/batch_file_summaries`
* Base class: `EndpointWithHttpRequestI`
* `api_types`: `["builtin"]`
* `REQUIRED_ARGS`: `model_name` (str), `language` (`"pl"` | `"en"`), `files`
  (`List[{"name": str, "content": str}]`)
* `OPTIONAL_ARGS`: `stream` (bool, default `False`), `max_points` (int, default `5`),
  `style_hint` (optional str, e.g. `"concise, no marketing"`)

**System prompt (two language variants, template with placeholders)**

* `pl` – `SYSTEM_PROMPT_NAME["pl"] = "builtin/system/pl/batch-file-summaries"`:

  ```text
  Jesteś asystentem do analizy dokumentów. Dla KAŻDEGO wejściowego dokumentu zrób:
  1) 3–5 zdań podsumowania.
  2) Wypunktuj maksymalnie ##MAX_POINTS## kluczowych informacji.
  3) Styl: ##STYLE_HINT##.
  Odpowiadaj precyzyjnie i operuj tylko na przekazanej treści.
  ```

* `en` – `SYSTEM_PROMPT_NAME["en"] = "builtin/system/en/batch-file-summaries"`:

  ```text
  You are a document analysis assistant. For EACH input document:
  1) Provide a 3–5 sentence summary.
  2) Bullet up to ##MAX_POINTS## key points.
  3) Style: ##STYLE_HINT##.
  Be precise and rely only on the provided content.
  ```

**Hook wiring**

* `call_for_each_user_msg=True` – each file → its own `user` message → separate HTTP call.
* `map_prompt` (payload key):
    * `"##MAX_POINTS##"` ← `max_points`,
    * `"##STYLE_HINT##"` ← `style_hint` or `"neutral"` / `"neutralny"`.
* `_prepare_response_function(responses, contents)` – aggregates the per‑file answers into
  `[{name, summary, key_points: []}, …]`.

**Example request payload**

```json
{
  "model_name": "google/gemma-3-12b-it",
  "language": "pl",
  "files": [
    {
      "name": "umowa_1.txt",
      "content": "…"
    },
    {
      "name": "raport_q2.pdf",
      "content": "…"
    }
  ],
  "max_points": 5,
  "style_hint": "zwięźle i rzeczowo",
  "stream": false
}
```

**Example response**

```json
{
  "response": [
    {
      "name": "umowa_1.txt",
      "summary": "…",
      "key_points": [
        "…",
        "…"
      ]
    },
    {
      "name": "raport_q2.pdf",
      "summary": "…",
      "key_points": [
        "…",
        "…"
      ]
    }
  ],
  "generation_time": 1.234
}
```

**Implementation – Pydantic request model** (in `llm_router_lib/data_models/…`)

```python
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

# Required / optional argument lists for the endpoint
BFS_REQ: List[str] = ["model_name", "language", "files"]
BFS_OPT: List[str] = ["stream", "max_points", "style_hint"]


class BatchFileInput(BaseModel):
    name: str = Field(..., description="File name (e.g. report.pdf)")
    content: str = Field(..., description="Text content of the file")


class BatchFileSummariesModel(BaseModel):
    model_name: str
    language: str = Field(..., description="Language code: 'pl' or 'en'")
    files: List[BatchFileInput] = Field(..., description="Files to process")
    stream: bool = False
    max_points: int = 5
    style_hint: Optional[str] = None

    @field_validator("language")
    @classmethod
    def _lang_check(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in {"pl", "en"}:
            raise ValueError("language must be 'pl' or 'en'")
        return v

    @field_validator("max_points")
    @classmethod
    def _points_check(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("max_points must be > 0")
        return v
```

**Implementation – endpoint class** (in `llm_router_api/endpoints/…`)

```python
from typing import Any, Dict, List, Optional
import time

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_router_api.core.decorators import EP
from llm_router_api.core.model_handler import ModelHandler
from llm_router_api.base.constants import REST_API_LOG_LEVEL
from llm_router_api.endpoints.endpoint_i import EndpointWithHttpRequestI
from llm_router_lib.data_models import (
    BatchFileSummariesModel,
    BFS_REQ,
    BFS_OPT,
)


class BatchFileSummariesHandler(EndpointWithHttpRequestI):
    """
    POST /api/batch_file_summaries

    Processes a list of files (each as a separate user message) and returns
    the list of summaries plus key points.
    """

    REQUIRED_ARGS = BFS_REQ
    OPTIONAL_ARGS = BFS_OPT
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/batch-file-summaries",
        "en": "builtin/system/en/batch-file-summaries",
    }

    def __init__(
            self,
            logger_file_name: Optional[str] = None,
            logger_level: Optional[str] = REST_API_LOG_LEVEL,
            prompt_handler: Optional[PromptHandler] = None,
            model_handler: Optional[ModelHandler] = None,
            ep_name: str = "batch_file_summaries",
    ):
        super().__init__(
            ep_name=ep_name,
            api_types=["builtin"],
            method="POST",
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=False,
            direct_return=False,
            call_for_each_user_msg=True,
        )

        # Aggregation hook for the per‑file results (mandatory in this mode)
        self._prepare_response_function = self._prepare_batch_response

        # buffer of file names (indices aligned with the user messages)
        self._file_names: List[str] = []

    @EP.require_params
    def prepare_payload(self, params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Build the backend payload:
        - maps model_name -> model
        - prepares messages: one user message per file
        - injects the system‑prompt overrides (max_points, style_hint)
        """
        options = BatchFileSummariesModel(**(params or {}))
        payload = options.model_dump()

        # prompt placeholder substitutions (internal key, popped before the HTTP call)
        style_hint = (payload.get("style_hint") or "").strip()
        out: Dict[str, Any] = {
            "model": payload["model_name"],
            "stream": bool(payload.get("stream", False)),
            # one USER message per file (required by call_for_each_user_msg)
            "messages": [{"role": "user", "content": f["content"]} for f in payload["files"]],
            "map_prompt": {
                "##MAX_POINTS##": str(payload["max_points"]),
                "##STYLE_HINT##": style_hint
                                  or ("neutralny" if payload["language"] == "pl" else "neutral"),
            },
        }

        # keep the file names for the aggregation step
        self._file_names = [f["name"] for f in payload["files"]]
        return out

    def _prepare_batch_response(self, responses: List[Any], contents: List[str]) -> Dict[str, Any]:
        """
        Aggregate the per‑file answers.

        responses : List[requests.Response]
        contents  : List[str]  (file contents, same order as the messages)
        """
        assert len(responses) == len(contents) == len(self._file_names)

        result = []
        for idx, response in enumerate(responses):
            _, _, text = self._get_choices_from_response(response=response)
            parsed = self._parse_summary_and_points(text)
            result.append(
                {
                    "name": self._file_names[idx],
                    "summary": parsed["summary"],
                    "key_points": parsed["key_points"],
                }
            )

        return {
            "response": result,
            "generation_time": time.time() - (self._start_time or time.time()),
        }

    @staticmethod
    def _parse_summary_and_points(text: str) -> Dict[str, Any]:
        """
        Simple heuristic: expect the sections
            Summary: / Podsumowanie:
            Key points: / Kluczowe punkty:
        If the model returns something else, the whole text becomes the summary.
        """
        if not text:
            return {"summary": "", "key_points": []}

        t = text.strip()
        lower = t.lower()
        markers = [
            ("podsumowanie:", "kluczowe punkty:"),
            ("summary:", "key points:"),
        ]

        for sum_m, pts_m in markers:
            i_sum = lower.find(sum_m)
            i_pts = lower.find(pts_m)
            if i_sum != -1 and i_pts != -1 and i_sum < i_pts:
                sum_part = t[i_sum + len(sum_m): i_pts].strip()
                pts_part = t[i_pts + len(pts_m):].strip()
                key_points = [p.strip(" -•\t").strip() for p in pts_part.splitlines() if p.strip()]
                key_points = [p for p in key_points if len(p)]
                return {"summary": sum_part, "key_points": key_points}

        # fallback – treat the whole text as the summary
        return {"summary": t, "key_points": []}
```

**Variant without binary files**

* The endpoint assumes `"files"` already contains text (e.g. OCR/extraction happened earlier).
* If file upload is added later, the text‑extraction layer must be inserted **before** the LLM calls (separately from
  this endpoint).

---

## See Also

* [Endpoint catalog (EN)](../endpoints/README.md) – the full list of registered endpoints, authentication scopes and
  streaming notes.
* [Models configuration](MODELS_CONFIG.md) – how models/providers are defined.
* [Load‑balancing strategies](LB_STRATEGIES.md) – provider selection per request.
* [Authentication](AUTHENTICATION.md) – API keys, policies and endpoint permissions.
* [Environment variables](ENV_DEFINITIONS.md) – all `LLM_ROUTER_*` settings (prefix, prompts dir, timeouts, default
  language, …).
