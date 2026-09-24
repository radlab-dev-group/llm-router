"""LLM Router Library.

A type-safe Python client for the LLM Router API that provides:

* :class:`LLMRouterClient` — high-level client with retry handling, unified
  error translation and a convenient payload builder.
* :class:`AsyncLLMRouterClient` — the ``asyncio``/``httpx`` counterpart with
  the same contract plus streaming conversation methods.
* Pydantic data models describing every request payload (conversation,
  translation, article generation, etc.) — see ``llm_router_lib.data_models``.
* An exception hierarchy for structured error handling.

Installation
------------

.. code-block:: bash

    pip install llm-router[lib]

Quick start
-----------

.. code-block:: python

    from llm_router_lib import LLMRouterClient

    with LLMRouterClient(api="http://localhost:8080", token="my-token") as client:
        result = client.conversation_with_model(
            user_last_statement="Hello!",
            model="google/gemma-3-12b-it",
        )

Asynchronous applications (e.g. FastAPI) should use
:class:`AsyncLLMRouterClient` instead (requires ``httpx``, installed with the
API requirements)::

    from llm_router_lib import AsyncLLMRouterClient

    async with AsyncLLMRouterClient(api="http://localhost:8080", token="my-token") as client:
        async for event in client.stream_conversation_with_model(
            user_last_statement="Hello!",
            model="google/gemma-3-12b-it",
        ):
            print(event.text, end="", flush=True)

For full API reference, see the :class:`LLMRouterClient` docstring and the
:data_models:`data‑models package <llm_router_lib.data_models>`.
"""

from llm_router_lib.client import LLMRouterClient
from llm_router_lib.async_client import AsyncLLMRouterClient
from llm_router_lib.exceptions import (
    LLMRouterError,
    AuthenticationError,
    RateLimitError,
    ValidationError,
)

__all__ = [
    # Public client
    "LLMRouterClient",
    "AsyncLLMRouterClient",
    # Exception hierarchy
    "LLMRouterError",
    "AuthenticationError",
    "RateLimitError",
    "ValidationError",
]
