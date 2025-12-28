"""
Request model for the OpenAI‑compatible chat endpoint.

The model mirrors the JSON schema accepted by the official OpenAI
``/v1/chat/completions`` API, enriched with a few router‑specific defaults
such as ``keep_alive`` and a language fallback.  It inherits the generic
generation options from :class:`BaseModelOptions`.
"""

from typing import List, Dict, Any

from llm_router_api.base.constants_base import DEFAULT_EP_LANGUAGE
from llm_router_lib.data_models.base_model import BaseModelOptions


class OpenAIChatModel(BaseModelOptions):
    """
    Payload model for the OpenAI chat completion endpoint.

    Attributes
    ----------
    model : str
        Identifier of the model to be used (e.g. ``"gpt-4o"``).
    messages : List[Dict[str, Any]]
        Conversation history in the OpenAI format – each entry must contain a
        ``role`` (``"system"``, ``"user"``, or ``"assistant"``) and a ``content``
        string.
    stream : bool, default ``True``
        When ``True`` the endpoint returns a streaming response (Server‑Sent
        Events).  Setting it to ``False`` yields a single JSON payload.
    keep_alive : str, default ``"30m"``
        Duration for which the model’s session should be kept alive on the
        backend.  The value follows the OpenAI convention (e.g. ``"30m"``,
        ``"1h"``).
    language : str, default ``DEFAULT_EP_LANGUAGE``
        Language code used by the router for any language‑specific handling.
    options : Dict[str, Any], default ``{"num_ctx": 128000}``
        Arbitrary additional parameters that are passed straight to the
        downstream provider.  The default sets a generous context window.
    """

    model: str
    messages: List[Dict[str, Any]]

    stream: bool = True
    keep_alive: str = "30m"
    language: str = DEFAULT_EP_LANGUAGE

    options: Dict[str, Any] = {"num_ctx": 128000}


# Names of required fields for ``OpenAIChatModel``.
OPENAI_CHAT_REQ_ARGS = ["model", "messages"]

# Names of optional fields for ``OpenAIChatModel``.
OPENAI_CHAT_OPT_ARGS = ["stream", "keep_alive", "language", "options"]
