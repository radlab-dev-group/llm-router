"""
Utility service wrappers for built‑in endpoints.

The file defines thin subclasses of :class:`BaseConversationServiceInterface`
that bind a concrete HTTP endpoint and the Pydantic model used for payload
validation.  These services can be instantiated with a ``HttpRequester`` and
a logger and then called via the ``.call()`` method provided by the base
class.
"""

from llm_router_lib.data_models.builtin_utils import TranslateTextModel
from llm_router_lib.services.conversation import BaseConversationServiceInterface


class TranslateTextService(BaseConversationServiceInterface):
    """
    Service for the ``/api/translate`` endpoint.

    The service posts a payload validated by :class:`TranslateTextModel` to the
    translation endpoint and returns the parsed JSON response.  All request
    handling (including error conversion to :class:`LLMRouterError`) is
    inherited from :class:`BaseConversationServiceInterface`.

    Attributes
    ----------
    endpoint : str
        Relative URL of the translation endpoint (``"/api/translate"``).
    model_cls : type
        The Pydantic model class used to validate request data
        (:class:`TranslateTextModel`).
    """

    endpoint = "/api/translate"
    model_cls = TranslateTextModel
