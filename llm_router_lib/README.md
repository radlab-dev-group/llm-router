# llm_router_lib

## Overview

`llm_router_lib` bundles **Pydantic data‑model definitions** **and** a **thin, opinionated client wrapper** for the
LLM‑Router service.

- The **data models** live in `llm_router_lib/data_models` and describe every request payload the router accepts.
- The **client** (`LLMRouterClient`) offers a high‑level, Pythonic API that hides HTTP details, retries, and error
  handling.
- Low‑level **service classes** (`ConversationWithModelService`, `ExtendedConversationWithModelService`,
  `TranslateService`,
  `GenerativeAnswerService`, health services) perform the actual HTTP calls and can be used directly when finer‑grained
  control is required.
- `HttpRequester` (in `utils/http.py`) is a small wrapper around `requests` that adds logging, configurable retries, and
  unified error translation.
- A dedicated **exception hierarchy** (`exceptions.py`) maps HTTP errors to meaningful Python exceptions.

In short, `llm_router_lib` provides **both** the contract (the “schema”) **and** a convenient client to consume the
router service.

## Installation

The library targets **Python 3.10.6** and uses a `virtualenv`. Install it in editable mode for development:

```bash

# Clone the repository (if you haven't already)

git clone https://github.com/radlab-dev-group/llm-router.git
cd llm-router/llm_router_lib

# Create and activate a virtual environment

python3 -m venv .venv
source .venv/bin/activate

# Install the package and its dependencies

pip install -e .
```

All runtime dependencies (`requests`, `pydantic`, plus the packages listed in `requirements.txt`) are declared in the
project’s `requirements.txt`.

## Quick start

```python
from llm_router_lib import LLMRouterClient

# Initialise the client – point it at the router’s host (do **not** include the `/api` prefix)

client = LLMRouterClient(
    api="http://localhost:8080",  # router host URL
    token="YOUR_ROUTER_TOKEN",  # optional, if router requires auth
)

# Call the standard conversation endpoint with named keyword arguments –
# the client builds the Pydantic request model for you.

response = client.conversation_with_model(
    user_last_statement="Hello, how are you?",
    model="google/gemma-3-12b-it",
    temperature=0.7,
    max_new_tokens=128,
)

# response is a typed `ConversationResponse` model:
print(response.response)  # → the assistant's reply text
print(response.generation_time)  # → seconds taken by the server
```

You can also pass a ready‑made `pydantic` request model via the `payload`
keyword (all endpoint parameters are keyword‑only – there are no positional arguments):

```python
from llm_router_lib.data_models.builtin_chat import ConversationWithModelRequest

payload = ConversationWithModelRequest(
    model_name="google/gemma-3-12b-it",
    user_last_statement="Hello, how are you?",
    temperature=0.7,
    max_new_tokens=128,
)

response = client.conversation_with_model(payload=payload)
```

> **Note:** raw `dict` payloads are no longer accepted – passing a `dict` as
> `payload` raises `TypeError`. Build the matching Pydantic model explicitly
> (e.g. `ConversationWithModelRequest(**dict_payload)`) or use the named
> keyword arguments. Calling a generation method with neither `payload` nor
> enough named arguments raises `NoArgsAndNoPayloadError`.

## Data models

All request payloads are defined in `llm_router_lib/data_models`.  
A common base class supplies shared options:

```python
class BaseModelOptions(BaseModel):
    """Options shared across many endpoint models."""
    mask_payload: bool = False
    masker_pipeline: Optional[List[str]] = None
```

### Conversation models

| Model                                  | Required fields                     | Optional / extra fields                                   |
|----------------------------------------|-------------------------------------|-----------------------------------------------------------|
| `ConversationWithModelRequest`         | `model_name`, `user_last_statement` | `temperature`, `max_new_tokens`, `historical_messages`, … |
| `ExtendedConversationWithModelRequest` | All of the above + `system_prompt`  | –                                                         |

### Utility models (selected examples)

| Model                                 | Required fields                        | Optional fields (generation parameters)                                   |
|---------------------------------------|----------------------------------------|---------------------------------------------------------------------------|
| `GenerateQuestionsModel`              | `texts` + `model_name`                 | `number_of_questions`, generation opts                                    |
| `GenerateArticleFromTextModel`        | `text` + `model_name`                  | generation opts                                                           |
| `TranslateModel`                      | `texts` + `model_name`                 | generation opts                                                           |
| `GenerativeAnswerModel`               | `question_str`, `texts` + `model_name` | `doc_name_in_answer`, `question_prompt`, `system_prompt`, generation opts |
| `OpenAIChatModel` (OpenAI‑compatible) | `model`, `messages`                    | `stream`, `keep_alive`, `language`, `options`                             |
| `SimplifyTextModel`                   | `texts`, `model_name`                  | generation opts                                                           |
| `CreateFullArticleFromTextsModel`     | `user_query`, `texts`, `model_name`    | `article_type`, generation opts                                           |
| `GenerateLabelModel`                  | `texts` + `model_name`                 | generation opts                                                           |

*(All utility models inherit from `BaseModelOptions` and therefore share the `mask_payload` and `masker_pipeline`
flags.)*

## Services (low‑level wrappers)

If you need direct access to the HTTP layer, the library exposes a set of service classes in `llm_router_lib/services`:

| Service class                          | Endpoint (relative to `api`)            | Payload model (if any)                 |
|----------------------------------------|-----------------------------------------|----------------------------------------|
| `ConversationWithModelService`         | `/api/conversation_with_model`          | `ConversationWithModelRequest`         |
| `ExtendedConversationWithModelService` | `/api/extended_conversation_with_model` | `ExtendedConversationWithModelRequest` |
| `TranslateService`                     | `/api/translate`                        | `TranslateModel`                       |
| `SimplifyTextService`                  | `/api/simplify_text`                    | `SimplifyTextModel`                    |
| `GenerativeAnswerService`              | `/api/generative_answer`                | `GenerativeAnswerModel`                |
| `GenerateQuestionsService`             | `/api/generate_questions`               | `GenerateQuestionsModel`               |
| `GenerateLabelService`                 | `/api/generate_label`                   | `GenerateLabelModel`                   |
| `PingService`                          | `/api/ping`                             | *none*                                 |
| `VersionService`                       | `/api/version`                          | *none*                                 |

These services inherit from `BaseConversationServiceInterface`, which provides `call_post` and `call_get` helpers that
perform JSON parsing and raise the library‑specific exceptions on failure.

### Example: using a service directly

```python
from llm_router_lib.services.conversation import ConversationWithModelService
from llm_router_lib.utils.http import HttpRequester
import logging

http = HttpRequester(base_url="http://localhost:8080", token="...", timeout=10)
logger = logging.getLogger("demo")

service = ConversationWithModelService(http, logger)
payload = {
    "model_name": "google/gemma-3-12b-it",
    "user_last_statement": "Hi!",
}
response = service.call_post(payload)
print(response)
```

## Thin client wrapper (`LLMRouterClient`)

`LLMRouterClient` aggregates the low‑level services and exposes a concise, high‑level API:

Every endpoint method shares **one keyword‑only calling contract**: pass a pre‑built Pydantic request model via
`payload=…`, **or** pass the named domain arguments (plus `model` and optional `temperature` / `max_new_tokens`) and the
client builds the request model for you. Raw `dict` payloads are rejected (`TypeError`); generation defaults come from
the Pydantic models. Calling a generation method with neither `payload` nor enough named arguments raises
`NoArgsAndNoPayloadError`.

| Method                                  | Endpoint                                     | Domain arguments (all keyword‑only)                                                                     |
|-----------------------------------------|----------------------------------------------|---------------------------------------------------------------------------------------------------------|
| `conversation_with_model(...)`          | `POST /api/conversation_with_model`          | `user_last_statement`, `historical_messages`, `model`, `temperature`, `max_new_tokens`                  |
| `extended_conversation_with_model(...)` | `POST /api/extended_conversation_with_model` | `user_last_statement`, `historical_messages`, `system_prompt`, `model`, `temperature`, `max_new_tokens` |
| `polarity_3c(...)`                      | `POST /api/polarity_3c`                      | `texts`, `model`, `temperature`, `max_new_tokens`                                                       |
| `translate(...)`                        | `POST /api/translate`                        | `texts`, `model`, `temperature`, `max_new_tokens`                                                       |
| `simplify_text(...)`                    | `POST /api/simplify_text`                    | `texts`, `model`, `temperature`, `max_new_tokens`                                                       |
| `generative_answer(...)`                | `POST /api/generative_answer`                | `texts`, `question_str`, `model`, `temperature`, `max_new_tokens`                                       |
| `generate_article_from_text(...)`       | `POST /api/generate_article_from_text`       | `text`, `model`, `temperature`, `max_new_tokens`                                                        |
| `generate_article_from_texts(...)`      | `POST /api/generate_article_from_texts`      | `texts`, `model`, `temperature`, `max_new_tokens`                                                       |
| `create_full_article_from_texts(...)`   | `POST /api/create_full_article_from_texts`   | `user_query`, `texts`, `article_type`, `model`, `temperature`, `max_new_tokens`                         |
| `generate_questions(...)`               | `POST /api/generate_questions`               | `texts`, `number_of_questions`, `model`, `temperature`, `max_new_tokens`                                |
| `generate_label(...)`                   | `POST /api/generate_label`                   | `texts`, `model`, `temperature`, `max_new_tokens`                                                       |
| `ping()`                                | `GET /api/ping`                              | – (health‑check endpoint)                                                                               |
| `version()`                             | `GET /api/version`                           | – (router version information)                                                                          |
| `models()`                              | `GET /v1/models`                             | – (available model list; use `.ids` / `.data`)                                                          |

Every method above also accepts `payload=<RequestModel>` as the alternative to the named arguments (e.g.
`translate(payload=TranslateModel(...))`).

All methods return a **typed response model** (a Pydantic `BaseModel`) validated from the JSON body — see
[`RESPONSE_MODELS.md`](RESPONSE_MODELS.md) for the full reference and the method→model mapping. Call
`.model_dump()` on the result to get the plain `dict` back. Errors from the underlying HTTP layer are translated into
the following exceptions (defined in `exceptions.py`):

- `LLMRouterError` – base class for all library‑specific errors.
- `AuthenticationError` – HTTP 401/403 (invalid or missing token).
- `RateLimitError` – HTTP 429 (too many requests).
- `ValidationError` – HTTP 400 (malformed payload).
- `NoArgsAndNoPayloadError` – client‑side validation: raised when a generation method is called without `payload` and
  without enough named arguments.

:::tip **Field naming across models**

Models for the built‑in generative endpoints use ``model_name`` as the field key (e.g.
``ConversationWithModelRequest``). The OpenAI‑compatible endpoint model uses ``model`` instead, to match the official
OpenAI API schema:

| Model class                      | Key for model identifier |
|----------------------------------|--------------------------|
| ``ConversationWithModelRequest`` | ``model_name``           |
| ``OpenAIChatModel``              | ``model``                |

:::

:::tip **Context manager support**

All public types (`LLMRouterClient`, `HttpRequester`) implement ``__enter__`` / ``__exit__``, so they can be used with
the
``with`` statement to guarantee resource cleanup:

```python
from llm_router_lib import LLMRouterClient

with LLMRouterClient(api="http://localhost:8080", token="...") as client:
    result = client.conversation_with_model(  # session closed automatically
        user_last_statement="Hi!",
        model="google/gemma-3-12b-it",
    )
```

:::

## Utilities

- **`utils/http.py` – `HttpRequester`**  
  Handles URL construction, bearer‑token injection, configurable retries (via `urllib3.Retry`), and unified error
  mapping. It returns the raw `requests.Response` after validation.

- **`exceptions.py`** – centralised exception definitions (see above).

## Development & testing

The repository includes a small test harness under `llm_router_lib/tests`. Example usage:

```bash
python -m llm_router_lib.tests.llm_router_client
```

This script spins up a `LLMRouterClient` instance and runs a suite of end‑to‑end tests covering conversation, extended
conversation, translation, generative answering, and health checks.
