# llm_router_lib

## Overview

`llm_router_lib` bundles **Pydantic data‑model definitions** **and** a **thin, opinionated client wrapper** for the
LLM‑Router service.

- The **data models** live in `llm_router_lib/data_models` and describe every request payload the router accepts.
- The **client** (`LLMRouterClient`) offers a high‑level, Pythonic API that hides HTTP details, retries, and error
  handling.
- Low‑level **service classes** (`ConversationService`, `ExtendedConversationService`, `TranslateTextService`,
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

# Build a payload using the provided data model (validation is automatic)

payload = {
    "model_name": "google/gemma-3-12b-it",
    "user_last_statement": "Hello, how are you?",
    "temperature": 0.7,
    "max_new_tokens": 128,
}

# Call the standard conversation endpoint

response = client.conversation_with_model(payload)

print(response)  # → {'status': True, 'body': {...}}
```

You can also pass a `pydantic` model instance directly:

```python
from llm_router_lib.data_models.builtin_chat import GenerativeConversationModel

model = GenerativeConversationModel(
    model_name="google/gemma-3-12b-it",
    user_last_statement="Hello, how are you?",
    temperature=0.7,
    max_new_tokens=128,
)

response = client.conversation_with_model(model)
```

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

| Model                                 | Required fields                     | Optional / extra fields                                   |
|---------------------------------------|-------------------------------------|-----------------------------------------------------------|
| `GenerativeConversationModel`         | `model_name`, `user_last_statement` | `temperature`, `max_new_tokens`, `historical_messages`, … |
| `ExtendedGenerativeConversationModel` | All of the above + `system_prompt`  | –                                                         |

### Utility models (selected examples)

| Model                                 | Required fields                        | Optional fields (generation parameters)                                   |
|---------------------------------------|----------------------------------------|---------------------------------------------------------------------------|
| `GenerateQuestionFromTextsModel`      | `texts` + `model_name`                 | `number_of_questions`, generation opts                                    |
| `GenerateArticleFromTextModel`        | `text` + `model_name`                  | generation opts                                                           |
| `TranslateTextModel`                  | `texts` + `model_name`                 | generation opts                                                           |
| `AnswerBasedOnTheContextModel`        | `question_str`, `texts` + `model_name` | `doc_name_in_answer`, `question_prompt`, `system_prompt`, generation opts |
| `OpenAIChatModel` (OpenAI‑compatible) | `model`, `messages`                    | `stream`, `keep_alive`, `language`, `options`                             |

*(All utility models inherit from `BaseModelOptions` and therefore share the `mask_payload` and `masker_pipeline`
flags.)*

## Services (low‑level wrappers)

If you need direct access to the HTTP layer, the library exposes a set of service classes in `llm_router_lib/services`:

| Service class                 | Endpoint (relative to `api`)            | Payload model (if any)                |
|-------------------------------|-----------------------------------------|---------------------------------------|
| `ConversationService`         | `/api/conversation_with_model`          | `GenerativeConversationModel`         |
| `ExtendedConversationService` | `/api/extended_conversation_with_model` | `ExtendedGenerativeConversationModel` |
| `TranslateTextService`        | `/api/translate`                        | `TranslateTextModel`                  |
| `GenerativeAnswerService`     | `/api/generative_answer`                | `AnswerBasedOnTheContextModel`        |
| `PingService`                 | `/api/ping`                             | *none*                                |
| `VersionService`              | `/api/version`                          | *none*                                |

These services inherit from `BaseConversationServiceInterface`, which provides `call_post` and `call_get` helpers that
perform JSON parsing and raise the library‑specific exceptions on failure.

### Example: using a service directly

```python
from llm_router_lib.services.conversation import ConversationService
from llm_router_lib.utils.http import HttpRequester
import logging

http = HttpRequester(base_url="http://localhost:8080", token="...", timeout=10)
logger = logging.getLogger("demo")

service = ConversationService(http, logger)
payload = {
    "model_name": "google/gemma-3-12b-it",
    "user_last_statement": "Hi!",
}
response = service.call_post(payload)
print(response)
```

## Thin client wrapper (`LLMRouterClient`)

`LLMRouterClient` aggregates the low‑level services and exposes a concise, high‑level API:

| Method                                                                                                                   | Description                                                                                                                                                                                     |
|--------------------------------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `conversation_with_model(payload)`                                                                                       | Calls `/api/conversation_with_model`. Accepts a dict **or** a `GenerativeConversationModel`.                                                                                                    |
| `extended_conversation_with_model(payload)`                                                                              | Calls `/api/extended_conversation_with_model`. Accepts a dict **or** an `ExtendedGenerativeConversationModel`.                                                                                  |
| `translate(payload=None, texts=None, model=None)`                                                                        | Calls `/api/translate`. Three usage patterns: <br>1️⃣ Pass a ready‑made dict.<br>2️⃣ Pass a `TranslateTextModel` instance.<br>3️⃣ Provide `texts` + `model` and let the client build the model. |
| `generative_answer(payload=None, model=None, texts=None, question_str=None)`                                             | Calls `/api/generative_answer`. Works with a dict, a `AnswerBasedOnTheContextModel` instance, or explicit arguments.                                                                            |
| `ping()`                                                                                                                 | Calls `/api/ping` – health‑check endpoint.                                                                                                                                                      |
| `version()`                                                                                                              | Calls `/api/version` – retrieves router version information.                                                                                                                                    |
| `translate(...)` and `generative_answer(...)` also raise `NoArgsAndNoPayloadError` if called without required arguments. |

All methods return the parsed JSON response (a `dict`). Errors from the underlying HTTP layer are translated into the
following exceptions (defined in `exceptions.py`):

- `LLMRouterError` – base class for all library‑specific errors.
- `AuthenticationError` – HTTP 401/403 (invalid or missing token).
- `RateLimitError` – HTTP 429 (too many requests).
- `ValidationError` – HTTP 400 (malformed payload).
- `NoArgsAndNoPayloadError` – client‑side validation when required arguments are missing.

## Utilities

- **`utils/http.py` – `HttpRequester`**  
  Handles URL construction, bearer‑token injection, configurable retries (via `urllib3.Retry`), and unified error
  mapping. It returns the raw `requests.Response` after validation.

- **`exceptions.py`** – centralised exception definitions (see above).

## Development & testing

The repository includes a small test harness under `llm_router_lib/tests`. Example usage:

```bash
python -m llm_router_lib.tests.llm-router-client
```

This script spins up a `LLMRouterClient` instance and runs a suite of end‑to‑end tests covering conversation, extended
conversation, translation, generative answering, and health checks.
