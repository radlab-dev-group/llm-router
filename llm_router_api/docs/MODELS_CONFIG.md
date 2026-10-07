# Models configuration description (JSON)

## 📄 Purpose

This document explains the **model configuration** used by the LLM Router.  
It describes the JSON schema that drives **`ModelHandler`** and **`ApiModelConfig`**, clarifies each field, and provides
a ready‑to‑use example (`models-config.json`).  
Having a single source of truth for model definitions makes it easy to:

* Add or remove providers for a given model.
* Switch between cloud (OpenAI, Google) and local (vLLM, Ollama) back‑ends.
* Control load‑balancing, keep‑alive, and tool‑calling options per provider.
* Activate only the models you want to expose through the router.

---  

## 🏗️ High‑level structure

```
{
  "<model_type>": {               # e.g. "google_models", "openai_models", "qwen_models"
    "<model_name>": {            # full identifier used by the router, e.g. "google/gemma-3-12b-it"
      "providers": [ … ],        # primary providers (used for normal traffic)
      "providers_sleep": [ … ]   # optional low‑priority providers (used when others are busy)
      "fallback_model": "…"      # optional model used when no provider can serve this one
    },
    …
  },
  "active_models": {              # **required** – tells the router which models are enabled
    "<model_type>": [ "<model_name>", … ],
    …
  }
}
```

* **Model type** – a top‑level key grouping models that share the same provider‑type logic.
* **Model name** – the identifier that appears in API calls (`model` field).
* **`providers`** – a list of dictionaries, each describing a concrete endpoint.
* **`providers_sleep`** (optional) – “sleeping” providers that are only used when all primary providers are unavailable
  or overloaded.
* **`fallback_model`** (optional) – name of another **active** model that takes over when no provider of this model can
  serve the request. See [Fallback model](#-fallback_model-model-level).
* **`active_models`** – the only place where a model is marked as *active*. If a model is missing here, the router will
  ignore it even if it is present in the rest of the file.

---  

## 🔎 Detailed field description

### Provider dictionary (items in `providers` / `providers_sleep`)

| Field          | Type                      | Description                                                                                                                         | Example                         |
|----------------|---------------------------|-------------------------------------------------------------------------------------------------------------------------------------|---------------------------------|
| `id`           | `str`                     | Unique identifier for the provider instance (used for logging & selection).                                                         | `"gemma3_12b-vllm-71:7000"`     |
| `api_host`     | `str`                     | Base URL of the provider API (must include protocol, may contain trailing slash).                                                   | `"http://192.168.100.71:7000/"` |
| `api_token`    | `str`                     | Authentication token; empty string if not required.                                                                                 | `""`                            |
| `api_type`     | `str`                     | Type of the backend – determines which concrete `BaseProvider` class is used (`openai`, `vllm`, `ollama`, …).                       | `"vllm"`                        |
| `input_size`   | `int` (or numeric string) | Maximum context length the provider accepts. The `ApiModel.from_config` helper converts it to `int`.                                | `4096`                          |
| `model_path`   | `str`                     | Path or name of the model on the provider side (used by Ollama, vLLM, etc.). May be empty for providers that infer it from the URL. | `"gpt-3.5-turbo-0125"`          |
| `weight`       | `float`                   | Relative weight for **weighted‑random** load‑balancing strategies. Default `1.0`.                                                   | `0.1`                           |
| `nworkers`     | `int` (or numeric string) | Maximum number of **concurrent requests** allowed on the provider. Used only by the `first_available_optim_nworkers` load‑balancing strategy; a missing, invalid or non‑positive value falls back to `1`. Read from the live configuration on every selection, so changing it takes effect on the next request — the health monitor's registration copy (`monitor:providers:<model>`) is not used for the limit. | `1`                             |
| `keep_alive`   | `str`                     | Optional keep‑alive duration (e.g. `"35m"`). Empty or `null` means the provider is not kept alive.                                  | `"35m"`                         |
| `tool_calling` | `bool`                    | Whether the provider supports tool‑calling (function calling).                                                                      | `true`                          |
| `is_embedding` | `bool`                    | Whether the model is an embedding model (determines use of embedding endpoints).                                                    | `true`                          |
| `provider_options` | `object` (optional)    | Provider‑specific options consumed only by the request adapter of the matching `api_type`. For `vertex_ai`: `project`, `region` (or `location`), `api_version` (default `v1`), `publisher` (default `google`), `api_key` (`x-goog-api-key`), `credentials_file` (service‑account JSON for Google ADC), `scopes`, plus `generation_config` / `safety_settings` merged into the Gemini request. For `bedrock`: `region` (or `aws_region`), `profile`, `access_key_id` / `secret_access_key` / `session_token` (static credentials for SigV4), `additional_model_request_fields` (merged in as `additionalModelRequestFields`), `guardrail_config` (passed through as `guardrailConfig`), and the embedding keys `embedding_input_type` (default `search_document` for Cohere v3, `input` for v4), `embedding_truncate` and `embedding_body` (exact request document). Never sent in the downstream payload, hidden from `/models`. | `{"project": "my-proj", "region": "europe-central2"}` |

### 🛟 `fallback_model` (model level)

A model may name another **active** model that takes over when none of its own providers can serve a request.
The switch happens **before load balancing**: the fallback model is handed to the load-balancing strategy, which then
picks one of *its* providers exactly like for any other request.

```json
{
  "qwen_models": {
    "qwen/Qwen3.8-Flash-Next": {
      "fallback_model": "qwen/qwen3-coder:30b",
      "providers": [
        {
          "id": "qwen3.8:flash-next-UD-IQ4_XL-70:7000",
          "api_host": "http://192.168.100.70:7000",
          "api_type": "llama.cpp",
          "input_size": 256000,
          "model_path": "qwen/Qwen3.8-Flash-Next"
        }
      ]
    },
    "qwen/qwen3-coder:30b": {
      "providers": [ "…" ]
    }
  }
}
```

* **When the fallback kicks in** – the requested model has no `providers` at all, the provider monitor reports no
  healthy provider for it, every provider stays busy until the strategy timeout (`TimeoutError`), or the strategy
  returns no provider, or **every provider of the model already failed this request** (a 4xx/5xx answer or a
  connection error, see [failover order](#-failover-order-providers-first-then-fallback_model)).
* **No extra waiting** – the health check that skips a model is used only when there is another model to try, so a
  model without `fallback_model` behaves exactly as before (it waits for the full strategy timeout and then reports
  the error).
* **Chains** – the fallback model may declare a `fallback_model` of its own (`a -> b -> c`). The last model of the
  chain keeps the normal blocking behaviour; when it fails too, its original error is reported to the client.
* **What the client sees** – the served model: the selected provider's `model_path`, or the fallback model name when
  `model_path` is empty.
* **Validated at startup** – an unknown target, a non-string value, a self reference or a cycle (`a -> b -> a`)
  abort the start with a `ValueError`; a missing, `null` or empty value simply means “no fallback”.
* **Observability** – every switch logs a `WARNING`, a fully exhausted chain logs an `ERROR` with the whole chain, and
  the `llm_router_model_fallback_total{model_name, fallback_model}` counter counts requests served by a fallback.
* **Not affected** – authentication/authorization, still checked against the model named by the client.
  Provider errors are not: they first rotate over the providers of the model and only then reach the fallback chain
  ([failover order](#-failover-order-providers-first-then-fallback_model)).

### 🔁 Failover order (providers first, then `fallback_model`)

A single request walks the chain provider by provider — the fallback model is the **last** resort, not the first:

1. the load-balancing strategy picks a provider of the requested model;
2. if that provider answers with an error (any 4xx/5xx, streaming included) or is unreachable, the request is
   replayed on **another provider of the same model**: the failed provider is remembered in the request options
   (`__attempted_providers`) and dropped from the candidates of every following attempt;
3. once the model has no untried provider left, the next model of the `fallback_model` chain is served — its own
   providers are rotated by the same rules;
4. when the whole chain is exhausted, the last provider error is returned to the client
   (`llm_router_retry_exhausted_total` counts it).

Streaming fails over the same way: the first chunk is awaited before the response starts, so a provider
that rejects the stream request (error status), never answers at all, or answers `200 OK` and drops the
connection before the first chunk exists, is swapped before the client sees a truncated answer. A failure
**mid-stream**, after bytes were already delivered, is never replayed: the client gets the provider's final
error chunk instead. Attempts are bounded by the retry policy
of the endpoint (`HttpDispatch.RetryPolicy.MAX_RECONNECTIONS`, default `10`); set
`RETRY_ON_ANY_ERROR_STATUS = False` on an endpoint's `RetryResponse` to restrict retries to the historical allow-list
(`429`, `500`, `502`, `503`, `504`).

### 🪶 Google Vertex AI (Gemini) providers

`api_type: "vertex_ai"` providers speak the native Vertex AI REST protocol
(`generateContent` / `streamGenerateContent?alt=sse` / `batchEmbedContents`).
Clients keep using the OpenAI‑shaped endpoints (`/v1/chat/completions`,
`/v1/embeddings`, …) — the router translates the request and the response,
including tool calling (`tools` ↔ `functionDeclarations` / `tool_calls`) and
multimodal content parts (text, `data:`‑URI images, `fileData` images).

The model resource path is built from `api_host` + `provider_options`:

* `api_host` = `https://REGION-aiplatform.googleapis.com` with
  `provider_options.project` / `provider_options.region` set, **or**
* `api_host` = the full
  `https://REGION-aiplatform.googleapis.com/v1/projects/{p}/locations/{r}`
  base (the prefix is then detected and not duplicated).

`model_path` is the model name (or a full `publishers/.../models/...`
resource). Authentication resolution order: `api_token` (`Bearer`) →
`provider_options.api_key` (`x-goog-api-key`) → Google Application Default
Credentials (optional `google` dependency — see
[ENV_DEFINITIONS](ENV_DEFINITIONS.md#google-vertex-ai-variables-optional)).
The provider health check pings the model resource (`GET`), so a misconfigured
project/region/credentials is reported as `auth_error` / `not_found` instead
of keeping the provider in the active pool.

#### Function calling round trip

Multi‑turn tool calling needs **both** directions of the OpenAI ↔ Gemini
translation, which the router performs as follows:

* `assistant.tool_calls` → Gemini `functionCall` parts (the JSON `arguments`
  string is parsed into `args`; an unparsable value degrades to `{}` with a
  warning instead of failing the request);
* `role: "tool"` → `functionResponse`, its `name` resolved from **`tool_call_id`**
  through the preceding assistant message (a legacy `name` field is still
  honoured, and the id wins when both are present);
* a tool message whose `tool_call_id` matches no earlier call is **dropped** with
  a warning — Gemini rejects a `functionResponse` naming a function that was
  never called, so keeping it would turn a trimmed history into a hard `400`;
* parallel calls (several `tool_calls`, several `role: "tool"` answers) are
  preserved, and results arrive in a single `user` turn;
* a turn that ended on a function call reports `finish_reason: "tool_calls"`,
  and `delta.tool_calls[].index` counts across chunks, so parallel calls stay
  distinct on the client side.

Set **`"tool_calling": true`** on a provider used with tools: without it the
router strips `tools` from the payload while the conversation history still
carries the calls, which Gemini rejects (the router logs a warning).

Thinking models attach an opaque `thoughtSignature` to their function calls,
which must be sent back on the next turn. The router surfaces it as
`tool_calls[].thought_signature` and re‑attaches it when the client echoes the
message back; clients that strip unknown fields from tool calls cannot use
function calling with those models through the router.

Streaming ends the way OpenAI clients expect: the router synthesises the
terminal chunk (Gemini's native SSE carries no `[DONE]` sentinel and may end
with an unmapped `finishReason`) and closes with `data: [DONE]`.

```json
{
  "google_models": {
    "google/gemini-2.5-flash-vertex": {
      "providers": [
        {
          "id": "vertex-gemini-2_5-flash",
          "api_host": "https://europe-central2-aiplatform.googleapis.com",
          "api_token": "YOUR_GOOGLE_ACCESS_TOKEN",
          "api_type": "vertex_ai",
          "input_size": 1048576,
          "model_path": "gemini-2.5-flash",
          "keep_alive": null,
          "tool_calling": true,
          "nworkers": 10,
          "provider_options": {
            "project": "YOUR_GCP_PROJECT_ID",
            "region": "europe-central2"
          }
        }
      ]
    }
  }
}
```

### 🪨 AWS Bedrock providers

`api_type: "bedrock"` providers speak the native Bedrock runtime protocol: the
**Converse API** for chat/completions/responses (`converse` /
`converse-stream`) and **`InvokeModel`** for embeddings — Converse has no
embeddings operation. Clients keep using the OpenAI‑shaped endpoints
(`/v1/chat/completions`, `/v1/embeddings`, …) — the router translates the
request and the answer, including tool calling and multimodal content parts.

Unlike the other types, the model is addressed **in the URL**, so the request
body never carries a `model` field:

* `/model/{modelId}/converse` – chat/completions/responses,
* `/model/{modelId}/converse-stream` – the same, streamed,
* `/model/{modelId}/invoke` – embeddings.

`api_host` is the region‑specific runtime endpoint
(`https://bedrock-runtime.eu-central-1.amazonaws.com`) and `model_path` is the
Bedrock model ID: a base model ID (`anthropic.claude-sonnet-4-20250514-v1:0`), a
cross‑region inference profile (`eu.anthropic.claude-…`) or a model ARN — all
accepted verbatim. Authentication resolution order:

1. `api_token` – a Bedrock API key, sent as `Authorization: Bearer <token>`; no
   dependency needed;
2. `provider_options.access_key_id` / `secret_access_key` / `session_token` –
   SigV4 signing; no dependency needed;
3. the `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_SESSION_TOKEN`
   environment variables – SigV4; no dependency needed;
4. the boto3 credential chain – shared config files and named profiles, SSO,
   assumed IAM roles, EKS Web Identity (IRSA) and the EC2/ECS metadata service –
   through the optional `aws` dependency (`pip install "radlab-llm-router[aws]"`,
   see [ENV_DEFINITIONS](ENV_DEFINITIONS.md#aws-bedrock-variables-optional));
   when boto3 is missing and the chain is needed, a `RuntimeError` with the
   install hint is raised.

Signing itself (SigV4), the Converse translation and the event‑stream decoder
use the Python standard library only — `boto3` is never in the request path, it
only supplies credentials.

There is no provider‑specific health‑check path: the Bedrock runtime offers no
cheap `GET`, so the monitor falls back to its generic probe list. A `401`/`403`
evicts chain‑resolved credentials from the cache, so the next request resolves
fresh ones instead of replaying a rejected credential until the process
restarts.

#### Parameters, tools and finish reasons

| OpenAI field                                       | Converse field                                                                                                                                           |
|----------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `temperature`                                      | `inferenceConfig.temperature`                                                                                                                            |
| `top_p`                                            | `inferenceConfig.topP`                                                                                                                                   |
| `max_tokens` / `max_completion_tokens`             | `inferenceConfig.maxTokens`                                                                                                                              |
| `stop`                                             | `inferenceConfig.stopSequences`                                                                                                                          |
| `tools[]`                                          | `toolConfig.tools[].toolSpec`, parameters under `inputSchema.json`                                                                                       |
| `tool_choice`                                      | `toolConfig.toolChoice`: `auto` → `{"auto":{}}`, `required` → `{"any":{}}`, `none` → `{"none":{}}`, a named function → `{"tool":{"name":…}}`              |
| `response_format` (`json_object` / `json_schema`)  | `outputConfig.textFormat`                                                                                                                                |

The `stopReason` of an answer maps to `finish_reason` as `end_turn` → `stop`,
`stop_sequence` → `stop`, `max_tokens` → `length`,
`model_context_window_exceeded` → `length`, `tool_use` → `tool_calls`,
`content_filtered` → `content_filter` and `guardrail_intervened` →
`content_filter`.

#### Messages and images

* The router **owns message normalisation** for Bedrock — Converse requires
  strictly alternating `user` / `assistant` turns, so consecutive same‑role
  messages are merged and `toolResult` blocks are preserved through the merge.
* Images must be supplied as base64 `data:` URLs: Bedrock does not fetch remote
  image URLs, and such parts are skipped with a warning.

#### Embeddings (`InvokeModel`)

The embedding body is model specific; the family is inferred from `model_path`
after stripping the regional prefixes (`eu.`, `apac.`, `us.`, `global.`):

* `amazon.titan-embed-text-v1` – `inputText`, one input per request;
* `amazon.titan-embed-text-v2:0` – `inputText` + optional `dimensions`;
* `amazon.nova-embed-v1:0` – `input.text`;
* `cohere.embed-*-v3` – `texts` + `input_type`, batch‑capable;
* `cohere.embed-v4:0` – `texts` + `input_type` + `embedding_types`.

An unrecognised embedding model raises a readable error naming the
`provider_options.embedding_body` override instead of guessing a body.

#### Streaming (`converse-stream`)

Bedrock answers `converse-stream` with `application/vnd.amazon.eventstream` — a
**binary** framing, not `text/event-stream` — which the router decodes natively
into OpenAI chunks. The frame CRC field deserves a caveat: the two AWS reference
implementations disagree about it (the published AWS encoding and `botocore` use
different byte ranges and a different seed), so the router accepts either
interpretation and does **not** validate the prelude CRC32C at all. The frame
lengths are self‑describing and the message CRC still covers the frame, so a
truncated or corrupted frame is rejected.

```json
{
  "aws_models": {
    "aws/claude-sonnet-4": {
      "providers": [
        {
          "id": "bedrock-claude-sonnet-4",
          "api_host": "https://bedrock-runtime.eu-central-1.amazonaws.com",
          "api_token": "",
          "api_type": "bedrock",
          "input_size": 200000,
          "model_path": "anthropic.claude-sonnet-4-20250514-v1:0",
          "keep_alive": null,
          "tool_calling": true,
          "nworkers": 10,
          "provider_options": {
            "region": "eu-central-1"
          }
        }
      ]
    },
    "aws/titan-embed-text-v2": {
      "providers": [
        {
          "id": "bedrock-titan-embed-v2",
          "api_host": "https://bedrock-runtime.eu-central-1.amazonaws.com",
          "api_token": "",
          "api_type": "bedrock",
          "input_size": 8192,
          "is_embedding": true,
          "model_path": "amazon.titan-embed-text-v2:0",
          "keep_alive": null,
          "nworkers": 10,
          "provider_options": {
            "region": "eu-central-1"
          }
        }
      ]
    }
  },
  "active_models": {
    "aws_models": [
      "aws/claude-sonnet-4",
      "aws/titan-embed-text-v2"
    ]
  }
}
```

With a Bedrock API key the credentials come from the provider itself, so no AWS
profile, environment variable or dependency is involved:

```json
{
  "id": "bedrock-claude-sonnet-4",
  "api_host": "https://bedrock-runtime.eu-central-1.amazonaws.com",
  "api_token": "YOUR_BEDROCK_API_KEY",
  "api_type": "bedrock",
  "input_size": 200000,
  "model_path": "anthropic.claude-sonnet-4-20250514-v1:0",
  "tool_calling": true,
  "provider_options": {
    "region": "eu-central-1"
  }
}
```

### `active_models` section

```json
{
  "active_models": {
    "google_models": [
      "google/gemma-3-12b-it",
      "google/gemini-2.5-flash-lite"
    ],
    "openai_models": [
      "openai/gpt-3.5-turbo-0125",
      "gpt-oss:20b",
      "gpt-oss:120b"
    ],
    "qwen_models": [
      "qwen3-coder:30b"
    ]
  }
}
```

* The **key** must match a top‑level model type defined elsewhere in the file.
* The **list** contains the exact model names that appear under that type.
* Only the models listed here are loaded by `ApiModelConfig._read_active_models()` and later exposed by `ModelHandler`.

---  

## 🧩 How `ModelHandler` uses the config

1. **Construction**

```python
handler = ModelHandler(
    models_config_path="/path/to/models-config.json",
    provider_chooser=my_provider_strategy
)
```

* `ApiModelConfig` reads the file, extracts `active_models`, and builds `models_configs` – a dict that maps each active
  model name to its full configuration (including the `providers` list).

2. **Fetching a provider**

```python
api_model = handler.get_model_provider("google/gemma-3-12b-it")
```

* `handler.api_model_config.models_configs[model_name]` returns the raw dict for the model.
* The `ProviderStrategyFacade` selects a concrete provider dict (based on the chosen load‑balancing algorithm).
* If no provider can serve the model (none configured, none healthy, or all busy until the strategy timeout) the
  handler walks the declared `fallback_model` chain and lets the strategy choose a provider of the next model.
* `ApiModel.from_config()` turns that dict into an `ApiModel` instance – a lightweight object that stores fields like
  `api_host`, `api_type`, `keep_alive`, etc.

3. **Listing active models**

```python
active = handler.list_active_models()
```

* Returns a dict grouped by model type, each entry containing a short, sanitized view of the primary provider (removing
  secret fields such as `api_token` and `model_path`).

---  

## 📦 Sample configuration (`models-config.json`)

Below is a trimmed version of the real file located in `resources/configs/models-config.json`.  
Copy it to your own configuration directory and adjust the values to match your environment.

```json
{
  "google_models": {
    "google/gemma-3-12b-it": {
      "providers": [
        {
          "id": "gemma3_12b-vllm-71:7000",
          "api_host": "http://192.168.100.71:7000/",
          "api_token": "",
          "api_type": "vllm",
          "input_size": 4096,
          "model_path": "",
          "weight": 1.0,
          "nworkers": 4,
          "keep_alive": null,
          "tool_calling": false
        },
        {
          "id": "gemma3_12b-vllm-71:7001",
          "api_host": "http://192.168.100.71:7001/",
          "api_token": "",
          "api_type": "vllm",
          "input_size": 4096,
          "model_path": "",
          "weight": 1.0,
          "nworkers": 4,
          "keep_alive": null,
          "tool_calling": false
        }
      ],
      "providers_sleep": [
        {
          "id": "gemma3_12b-vllm-66:7000",
          "api_host": "http://192.168.100.66:7000/",
          "api_token": "",
          "api_type": "vllm",
          "input_size": 4096,
          "model_path": "",
          "weight": 0.1,
          "keep_alive": null,
          "tool_calling": false
        }
        /* … more sleeping providers … */
      ]
    },
    "google/gemini-2.5-flash-lite": {
      "providers": [
        {
          "id": "google_gemini_2_5-flash-lite",
          "api_host": "https://generativelanguage.googleapis.com/v1beta/openai/",
          "api_token": "YOUR_GOOGLE_API_KEY",
          "api_type": "openai",
          "input_size": 512000,
          "model_path": "gemini-2.5-flash-lite",
          "keep_alive": null,
          "tool_calling": true
        }
      ]
    }
  },
  "openai_models": {
    "openai/gpt-3.5-turbo-0125": {
      "providers": [
        {
          "id": "openai-gpt3_5-t-0125",
          "api_host": "https://api.openai.com",
          "api_token": "YOUR_OPENAI_KEY",
          "api_type": "openai",
          "input_size": 256000,
          "model_path": "gpt-3.5-turbo-0125",
          "keep_alive": null,
          "tool_calling": false
        }
      ]
    }
    /* … other OpenAI/Ollama models … */
  },
  "qwen_models": {
    "nomic-embed-text": {
      "providers": [
        {
          "id": "nomic-embed-text-ollama",
          "api_host": "http://192.168.100.66:11434",
          "api_token": "",
          "api_type": "ollama",
          "input_size": 2048,
          "is_embedding": true
        }
      ]
    },
    "qwen3-coder:30b": {
      "providers": [
        {
          "id": "qwen3-coder-30b-66:11434",
          "api_host": "http://192.168.100.66:11434",
          "api_token": "",
          "api_type": "ollama",
          "input_size": 256000,
          "model_path": "",
          "nworkers": 1,
          "keep_alive": "35m",
          "tool_calling": true
        }
        /* … second provider … */
      ]
    }
  },
  "active_models": {
    "google_models": [
      "google/gemma-3-12b-it",
      "google/gemini-2.5-flash-lite"
    ],
    "openai_models": [
      "openai/gpt-3.5-turbo-0125"
    ],
    "qwen_models": [
      "qwen3-coder:30b",
      "nomic-embed-text"
    ]
  }
}
```

> **Tip:**  
> *Keep the file name configurable through the environment variable `LLM_ROUTER_MODELS_CONFIG` (the default is
`resources/configs/models-config.json`).*

---  

## 🎉 Summary

* **`models-config.json`** is the single source of truth for every LLM provider used by the router.
* **`active_models`** decides which models are exposed.
* **`ModelHandler` + `ApiModelConfig`** read the file, pick a provider according to the configured strategy, and hand
  you a ready‑to‑use `ApiModel` instance.
* **`fallback_model`** keeps a model servable when its own providers are down: the request is rerouted before load
  balancing and balanced over the providers of the fallback model.
* The sample configuration below can be copied and tweaked to fit your own deployment.

Feel free to edit this file whenever you add new providers or change load‑balancing weights – the router picks up the
changes on the next start (or after re‑loading the handler in a running process). Happy modeling!
