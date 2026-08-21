"""Service layer for built‑in HTTP endpoints.

This subpackage provides thin wrappers around individual API endpoints as
concrete subclasses of :class:`BaseConversationServiceInterface`.  Each service
binds an endpoint URL and a Pydantic model class for payload validation.
"""

from llm_router_lib.services.service_interface import (
    BaseConversationServiceInterface,
)
from llm_router_lib.services.conversation import (
    ConversationService,
    ExtendedConversationService,
)
from llm_router_lib.services.health import PingService, VersionService
from llm_router_lib.services.utils import (
    Polarity3cService,
    TranslateTextService,
    GenerativeAnswerService,
    GenerateNewsFromTextService,
    CreateFullArticleFromTextsService,
    GenerateArticleFromTextsService,
)

__all__ = [
    "BaseConversationServiceInterface",
    "ConversationService",
    "ExtendedConversationService",
    "PingService",
    "VersionService",
    "Polarity3cService",
    "TranslateTextService",
    "GenerativeAnswerService",
    "GenerateNewsFromTextService",
    "CreateFullArticleFromTextsService",
    "GenerateArticleFromTextsService",
]
