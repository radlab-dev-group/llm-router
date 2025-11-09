# llm‑router — Python client library

**llm‑router** is a lightweight Python client for interacting with the LLM‑Router API.  
It provides typed request models, convenient service wrappers, and robust error handling so you can focus on building
LLM‑driven applications rather than dealing with raw HTTP calls.

---  

## Table of Contents

1. [Overview](#overview)
2. [Features](#features)
3. [Installation](#installation)
4. [Quick start](#quick-start)
5. [Core concepts](#core-concepts)
    - [Client](#client)
    - [Data models](#data-models)
    - [Services](#services)
    - [Utilities](#utilities)
    - [Error handling](#error-handling)
6. [Testing](#testing)
7. [Contributing](#contributing)
8. [License](#license)

---  

## Overview

`llm_router_lib` is the official Python SDK for the **LLM‑Router** project <https://github.com/radlab-dev-group/llm-router>.

It abstracts the HTTP layer behind a small, well‑typed API:

* **Typed payloads** built with *pydantic* (e.g., `GenerativeConversationModel`).
* **Service objects** that know the endpoint URL and the model class they expect.
* **Automatic token handling**, request retries, and exponential back‑off.
* **Rich exception hierarchy** (`LLMRouterError`, `AuthenticationError`, `RateLimitError`, `ValidationError`).

---  

## Features

| Feature                            | Description                                                                    |
|------------------------------------|--------------------------------------------------------------------------------|
| **Typed request/response models**  | Guarantees payload correctness at runtime using Pydantic.                      |
| **Built‑in conversation services** | Simple `conversation_with_model` and `extended_conversation_with_model` calls. |
| **Retry & timeout**                | Configurable request timeout and automatic retries with exponential back‑off.  |
| **Authentication**                 | Bearer‑token support; raises `AuthenticationError` on 401/403.                 |
| **Rate‑limit handling**            | Detects HTTP 429 and raises `RateLimitError`.                                  |
| **Extensible**                     | Add custom services or models by extending the base classes.                   |
| **Test suite**                     | Ready‑to‑run unit tests in `llm_router_lib/tests`.                             |

---  

## Installation

The library is pure Python and works with **Python 3.10+**.

```shell script
# Create a virtualenv (recommended)
python -m venv .venv
source .venv/bin/activate

# Install from the repository (editable mode)
pip install -e .
```

If you prefer a regular installation from a wheel or source distribution, use:

```shell script
pip install .
```

> **Note** – The project relies only on the packages listed in the repository’s `requirements.txt` 
> (pydantic, requests, etc.), all of which are installed automatically by `pip`.

---  

## Quick start

```python
from llm_router_lib.client import LLMRouterClient
from llm_router_lib.data_models.builtin_chat import GenerativeConversationModel

# Initialise the client (replace with your own endpoint and token)
client = LLMRouterClient(
    api="https://api.your-llm-router.com",
    token="YOUR_ACCESS_TOKEN"
)

# Build a request payload
payload = GenerativeConversationModel(
    model_name="google/gemma-3-12b-it",
    user_last_statement="Hello, how are you?",
    historical_messages=[{"user": "Hi"}],
    temperature=0.7,
    max_new_tokens=128,
)

# Call the API
response = client.conversation_with_model(payload)

print(response)  # → dict with the model's answer and metadata
```

### Extended conversation

```python
from llm_router_lib.data_models.builtin_chat import ExtendedGenerativeConversationModel

payload = ExtendedGenerativeConversationModel(
    model_name="google/gemma-3-12b-it",
    user_last_statement="Explain quantum entanglement.",
    system_prompt="Answer as a friendly professor.",
    temperature=0.6,
    max_new_tokens=256,
)

response = client.extended_conversation_with_model(payload)
print(response)
```

---  

## Core concepts

### Client

`LLMRouterClient` is the entry point. It handles:

* Base URL normalization.
* Optional bearer token injection.
* Construction of the internal `HttpRequester`.

All public methods accept either a **dict** or a **pydantic model**; models are automatically serialized with
`.model_dump()`.

### Data models

Located in `llm_router_lib/data_models/`.  
Key models:

| Model                                        | Purpose                                                           |
|----------------------------------------------|-------------------------------------------------------------------|
| `GenerativeConversationModel`                | Simple chat payload (model name, user message, optional history). |
| `ExtendedGenerativeConversationModel`        | Same as above, plus a `system_prompt`.                            |
| `GenerateQuestionFromTextsModel`             | Generate questions from a list of texts.                          |
| `TranslateTextModel`, `SimplifyTextModel`, … | Various utility models for text transformation.                   |
| `OpenAIChatModel`                            | Payload for direct OpenAI‑compatible chat calls.                  |

All models inherit from a common `_GenerativeOptions` base that defines temperature, token limits, language, etc.

### Services

Implemented in `llm_router_lib/services/`.  
Each service extends `_BaseConversationService` and defines:

* `endpoint` – the API path (e.g., `/api/conversation_with_model`).
* `model_cls` – the Pydantic model class used for validation.

The service’s `call()` method performs the HTTP POST and returns a parsed JSON dictionary, raising `LLMRouterError` on
malformed responses.

### Utilities

* `llm_router_lib/utils/http.py` – thin wrapper around `requests` with retry logic, response validation, and logging.
* Logging is integrated via the standard library `logging` module; you can inject your own logger when constructing the
  client.

### Error handling

| Exception             | When raised                                               |
|-----------------------|-----------------------------------------------------------|
| `LLMRouterError`      | Generic SDK‑level error (e.g., non‑JSON response).        |
| `AuthenticationError` | HTTP 401/403 – missing or invalid token.                  |
| `RateLimitError`      | HTTP 429 – the server throttled the request.              |
| `ValidationError`     | HTTP 400 – request payload failed server‑side validation. |

All exceptions inherit from `LLMRouterError`, allowing a single `except LLMRouterError:` clause to catch any SDK‑related
problem.

---

## License

`llm_router_lib` is released under the **MIT License**. See the `LICENSE` file for details.  