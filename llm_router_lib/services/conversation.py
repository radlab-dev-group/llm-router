"""
Service layer for invoking built‑in conversation endpoints.

The module defines a tiny abstract interface that knows how to POST a
payload to a specific HTTP endpoint using a ``HttpRequester`` instance.
Concrete subclasses bind the interface to the concrete endpoint URL and the
Pydantic model that validates the request payload.
"""

from llm_router_lib.data_models.builtin_chat import (
    ConversationWithModelRequest,
    ExtendedConversationWithModelRequest,
)
from llm_router_lib.services.service_interface import (
    BaseConversationServiceInterface,
)


class ConversationWithModelService(BaseConversationServiceInterface):
    """
    Concrete service for the standard conversation endpoint.

    Uses ``/api/conversation_with_model`` and validates payloads against
    :class:`ConversationWithModelRequest`.
    """

    endpoint = "/api/conversation_with_model"
    model_cls = ConversationWithModelRequest


class ExtendedConversationWithModelService(BaseConversationServiceInterface):
    """
    Concrete service for the extended conversation endpoint.

    Uses ``/api/extended_conversation_with_model`` and validates payloads
    against :class:`ExtendedConversationWithModelRequest`, which supports an
    explicit system prompt.
    """

    endpoint = "/api/extended_conversation_with_model"
    model_cls = ExtendedConversationWithModelRequest
