# llm_router_lib

## Overview

`llm_router_lib` is ** a collection of data‑model definitions**.
It supplies the **foundation** for request/response structures used by the
`llm_router_api` package **and** provides a **thin, opinionated client wrapper**
that makes interacting with the LLM Router service straightforward.

Key components:

| Package             | Purpose                                                                                                                                                                                                                                                                                                                                                    |
|---------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **`data_models`**   | `pydantic` models that define the shape of payloads sent to the router (e.g. `GenerativeConversationModel`, `ExtendedGenerativeConversationModel`, utility models for question generation, translation, etc.). These models are shared with the API side, ensuring both client and server speak the same contract.                                         |
| **`client.py`**     | `LLMRouterClient` – a lightweight wrapper around the router’s HTTP API. It offers high‑level methods (`conversation_with_model`, `extended_conversation_with_model`) that accept either plain dictionaries **or** the aforementioned data‑model instances. The client handles payload validation, provider selection, error mapping, and response parsing. |
| **`services`**      | Low‑level service classes (`ConversationService`, `ExtendedConversationService`) that perform the actual HTTP calls via `HttpRequester`. They are used internally by the client but can be reused directly if finer‑grained control is needed.                                                                                                             |
| **`exceptions.py`** | Custom exception hierarchy (`LLMRouterError`, `AuthenticationError`, `RateLimitError`, `ValidationError`) that mirrors the router’s error semantics, making error handling in user code clean and explicit.                                                                                                                                                |
| **`utils/http.py`** | `HttpRequester` – a small wrapper around `requests` providing retries, time‑outs and logging. It is the networking backbone for the client wrapper.                                                                                                                                                                                                        |

In short, `llm_router_lib` provides **both** the data contract (the “schema”) **and** a convenient Pythonic client to
consume the router service.

## Installation

The library targets **Python 3.10.6** and uses a `virtualenv`. Install it in editable mode for development:

``` bash
# Clone the repository (if you haven't already)
git clone https://github.com/radlab-dev-group/llm-router.git
cd llm-router/llm_router_lib

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install the package and its dependencies
pip install -e .
```

All runtime dependencies (`requests`, `pydantic`, `rdl_ml_utils`) are declared in the project’s `requirements.txt`.

## Quick start

``` python
from llm_router_lib import LLMRouterClient

# Initialise the client – point it at the router’s base URL
client = LLMRouterClient(
    api="http://localhost:8080/api",   # router base URL
    token="YOUR_ROUTER_TOKEN",         # optional, if router requires auth
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

print(response)   # → {'status': True, 'body': {...}}
```

You can also pass a `pydantic` model instance directly:

```
python
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
Common base:

``` python
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

Utility models for other built‑in endpoints (question generation, translation,
article creation, context‑based answering, etc.) follow the same pattern and
inherit from `BaseModelOptions`.

## Thin client wrapper (`LLMRouterClient`)

`LLMRouterClient` offers a **high‑level API** that abstracts away the low‑level
HTTP details:

| Method                                      | Description                                                                                                    |
|---------------------------------------------|----------------------------------------------------------------------------------------------------------------|
| `conversation_with_model(payload)`          | Calls `/api/conversation_with_model`. Accepts a dict **or** a `GenerativeConversationModel`.                   |
| `extended_conversation_with_model(payload)` | Calls `/api/extended_conversation_with_model`. Accepts a dict **or** an `ExtendedGenerativeConversationModel`. |

Internally the client:

1. **Validates** the payload (via the corresponding `pydantic` model if a model instance is supplied).
2. **Selects** an appropriate provider using the router’s load‑balancing
